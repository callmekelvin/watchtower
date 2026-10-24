import os
import re
from datetime import datetime, timezone

from PySide6.QtCore import QObject, Signal, Slot, QUrl, QTimer, QDateTime
from PySide6.QtMultimedia import QCamera, QCameraDevice, QMediaCaptureSession, QMediaDevices, QMediaFormat, QMediaMetaData, QMediaRecorder, QVideoSink

from backend.device_worker import _decode_id


# Create a filesystem-safe lower-case slug from a device description.
def _sanitize_filename(name: str) -> str:
    slug = name.lower().strip()
    slug = re.sub(r"[^a-z0-9]+", "-", slug)
    slug = slug.strip("-")
    return slug or "camera"

# Dedicated QThreadWorker that runs QMediaCaptureSession
# The session, camera, recorder, and a private QMediaDevices instance all live on this worker thread so that the GUI thread is never blocked.
class CaptureSessionWorker(QObject):
    # Emitted once the QMediaCaptureSession has been created (Arg: device_id, session)
    # Receivers must not call methods on the session object from another thread
    sessionReady = Signal(str, QObject)

    # Signal emitted when the worker encounters an error (Arg: device_id, message)
    errorOccurred = Signal(str, str)

    # Signal emitted after stop() has finished cleaning up (Arg: Device ID)
    stopped = Signal(str)

    # Emitted when the recording state changes (Arg: device_id, is_recording)
    recordingStateChanged = Signal(str, bool)

    # Emitted when a new segment file begins being written (Arg: device_id, file_path)
    segmentStarted = Signal(str, str)

    # Emitted when a segment file has been finalized (Arg: device_id, finalized_file_path)
    segmentFinalized = Signal(str, str)

    # Hardcoded segment duration: 15 minutes in milliseconds.
    _SEGMENT_DURATION_MS = 15 * 60 * 1000

    def __init__(self, device_id: str, parent: QObject | None = None):
        super().__init__(parent)
        self._device_id = device_id
        self._session: QMediaCaptureSession | None = None
        self._camera: QCamera | None = None
        self._recorder: QMediaRecorder | None = None
        self._media_devices: QMediaDevices | None = None
        self._video_sink: QVideoSink | None = None
        self._camera_device: QCameraDevice | None = None
        self._is_recording: bool = False

        self._segment_timer: QTimer = QTimer(self)
        self._segment_timer.setSingleShot(True)
        self._segment_timer.timeout.connect(self._on_segment_timer_timeout)

        self._output_folder: str | None = None
        self._active_output_path: str | None = None
        self._stop_requested: bool = False

    # Function - Called from Capture Session Manager Main Thread to
    @Slot(str, QVideoSink)
    def setVideoSink(self, device_id: str, sink: QVideoSink) -> None:
        # Invoked from the main thread; queued to the worker thread.
        if device_id != self._device_id:
            return
        self._video_sink = sink
        if self._session is not None:
            self._session.setVideoSink(sink)

    # Function - Detach this worker's session from its video sink.
    @Slot(str)
    def clearVideoSink(self, device_id: str) -> None:
        if device_id != self._device_id:
            return
        self._video_sink = None
        if self._session is not None:
            self._session.setVideoSink(None)

    @Slot()
    def initializeAndStart(self) -> None:
        try:
            # Each worker owns its own QMediaDevices instance to avoid sharing QMediaDevices across threads.
            self._media_devices = QMediaDevices(self)

            # Instantiate Media Capture Session and Recorder
            self._session = QMediaCaptureSession(self)
            self._recorder = QMediaRecorder(self)
            self._session.setRecorder(self._recorder)

            # Set Video Sink
            if self._video_sink is not None:
                self._session.setVideoSink(self._video_sink)

            # Notify the manager that the session object exists. The manager only
            # uses this to track that the worker has started; QML binds to the
            # video sink, not the session object.
            self.sessionReady.emit(self._device_id, self._session)

            # Find and store the corect QCameraDevice by Device ID
            self._camera_device = None
            for device in self._media_devices.videoInputs():
                if _decode_id(device.id()) == self._device_id:
                    self._camera_device = device
                    break

            # Emit error if No Camera is found
            if self._camera_device is None:
                self.errorOccurred.emit(
                    self._device_id, f"Camera '{self._device_id}' not found"
                )
                return

            # Configure QMediaRecorder for best available quality.
            self._configure_recorder(self._camera_device)

            # Create QCamera Object using QCameraDevice
            self._camera = QCamera(self._camera_device, self)
            self._camera.errorOccurred.connect(
                lambda _error, msg: self.errorOccurred.emit(
                    self._device_id, f"Camera error: {msg}"
                )
            )

            # Set QMediaCaptureSession to QCamera and Start Camera
            self._session.setCamera(self._camera)
            self._camera.start()
        except Exception as exc:
            self.errorOccurred.emit(self._device_id, str(exc))

    # Configure the recorder to use the camera's maximum resolution and frame rate.
    def _configure_recorder(self, camera_device: QCameraDevice) -> None:
        if self._recorder is None:
            return

        # Get and Set Best Resolution and Frame Rate for Recording
        formats = camera_device.videoFormats()
        if formats:
            best = max(
                formats,
                key=lambda fmt: (
                    fmt.resolution().width() * fmt.resolution().height(),
                    fmt.maxFrameRate(),
                ),
            )
            self._recorder.setVideoResolution(best.resolution())
            self._recorder.setVideoFrameRate(best.maxFrameRate())

        # Set to MPEG4 File Format and H264 Video Codec -> No Audio
        media_format = QMediaFormat(QMediaFormat.FileFormat.MPEG4)
        media_format.setVideoCodec(QMediaFormat.VideoCodec.H264)
        media_format.setAudioCodec(QMediaFormat.AudioCodec.Unspecified)
        self._recorder.setMediaFormat(media_format)
        self._recorder.setEncodingMode(QMediaRecorder.EncodingMode.ConstantQualityEncoding)

        self._recorder.recorderStateChanged.connect(self._on_recorder_state_changed)
        self._recorder.errorOccurred.connect(self._on_recorder_error)

    def _on_recorder_state_changed(self, state: QMediaRecorder.RecorderState) -> None:
        if state == QMediaRecorder.RecorderState.RecordingState:
            self._set_recording(True)
        elif state == QMediaRecorder.RecorderState.StoppedState:
            if self._stop_requested:
                old_path = self._active_output_path
                self._active_output_path = None
                if old_path:
                    self.segmentFinalized.emit(self._device_id, old_path)
                self._set_recording(False)
            else:
                self._start_next_segment()

    def _on_recorder_error(self, error: QMediaRecorder.Error, error_string: str) -> None:
        self.errorOccurred.emit(
            self._device_id, f"Recording error: {error_string or str(error)}"
        )
        self._set_recording(False)

    def _set_recording(self, is_recording: bool) -> None:
        if self._is_recording == is_recording:
            return
        self._is_recording = is_recording
        self.recordingStateChanged.emit(self._device_id, self._is_recording)

    def _generate_output_path(self, folder_path: str) -> str:
        name = _sanitize_filename(self._camera_device.description()) if self._camera_device else "camera"
        now = datetime.now(timezone.utc)
        timestamp = now.strftime("%Y%m%d_%H%M%S")
        ms = now.strftime("%f")[:3]
        filename = f"{name}_{timestamp}_{ms}.mp4"
        return os.path.join(folder_path, filename)

    def _ensure_output_folder(self, folder_path: str) -> bool:
        if os.path.isdir(folder_path):
            return True
        try:
            os.makedirs(folder_path, exist_ok=True)
            return True
        except Exception as exc:
            self.errorOccurred.emit(
                self._device_id, f"Failed to create output folder '{folder_path}': {exc}"
            )
            return False

    def _start_segment(self) -> bool:
        if self._recorder is None or self._output_folder is None:
            return False
        if not self._ensure_output_folder(self._output_folder):
            return False
        output_path = self._generate_output_path(self._output_folder)
        self._active_output_path = output_path
        self._recorder.setOutputLocation(QUrl.fromLocalFile(output_path))
        metadata = QMediaMetaData()
        metadata.insert(QMediaMetaData.Key.Author, ["watchtower_capture"])
        metadata.insert(QMediaMetaData.Key.Date, QDateTime.currentDateTimeUtc())
        self._recorder.setMetaData(metadata)
        self.segmentStarted.emit(self._device_id, output_path)
        self._recorder.record()
        return True

    def _start_next_segment(self) -> None:
        old_path = self._active_output_path
        if not self._start_segment():
            self.errorOccurred.emit(
                self._device_id, "Failed to rotate to next segment; recording stopped"
            )
            self._set_recording(False)
            return
        if old_path:
            self.segmentFinalized.emit(self._device_id, old_path)
        self._segment_timer.start(self._SEGMENT_DURATION_MS)

    def _on_segment_timer_timeout(self) -> None:
        if self._recorder is None or self._stop_requested or not self._is_recording:
            return
        self._recorder.stop()

    # Start recording video to the provided folder.
    @Slot(str, str)
    def startRecording(self, device_id: str, folder_path: str) -> None:
        if device_id != self._device_id:
            return
        try:
            if self._recorder is None:
                self.errorOccurred.emit(self._device_id, "Recorder not initialized")
                return

            if self._is_recording:
                return

            # Accept both local paths and file:// URLs from QML FolderDialog.
            url = QUrl(folder_path)
            local_path = url.toLocalFile() if url.isLocalFile() else folder_path

            if not local_path:
                self.errorOccurred.emit(
                    self._device_id, f"Invalid output folder: {folder_path}"
                )
                return

            self._stop_requested = False
            self._output_folder = local_path

            if not self._start_segment():
                self._set_recording(False)
                return

            self._segment_timer.start(self._SEGMENT_DURATION_MS)
        except Exception as exc:
            self.errorOccurred.emit(self._device_id, f"Failed to start recording: {exc}")
            self._set_recording(False)

    # Stop the current recording
    @Slot(str)
    def stopRecording(self, device_id: str) -> None:
        if device_id != self._device_id:
            return
        self._stop_requested = True
        self._segment_timer.stop()
        try:
            if self._recorder is not None and self._is_recording:
                self._recorder.stop()
        except Exception as exc:
            self.errorOccurred.emit(self._device_id, f"Failed to stop recording: {exc}")

    # Function called by Capture Session Manager when Capture Session Worker Thread is to be stopped/ terminated
    @Slot()
    def stop(self) -> None:
        # Stop Camera and Recorder
        # Then clear Camera and Recorder
        self._stop_requested = True
        self._segment_timer.stop()
        try:
            if self._recorder is not None and self._is_recording:
                self._recorder.stop()

            if self._camera is not None:
                self._camera.stop()
                self._camera.setParent(None)
                self._camera.deleteLater()
                self._camera = None

            if self._session is not None:
                self._session.setCamera(None)
                self._session.setVideoSink(None)
                self._session.setRecorder(None)
                self._session.setParent(None)
                self._session.deleteLater()
                self._session = None

            if self._recorder is not None:
                self._recorder.setParent(None)
                self._recorder.deleteLater()
                self._recorder = None

            self._media_devices = None
            self._video_sink = None
            self._camera_device = None
            self._output_folder = None
            self._active_output_path = None
            self._set_recording(False)
        except Exception as exc:
            # Notify Capture Session Manager Thread of termination error
            self.errorOccurred.emit(self._device_id, str(exc))
        finally:
            # Notify Capture Session Manager Thread has stopped
            self.stopped.emit(self._device_id)
