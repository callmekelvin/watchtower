import os
import re
from datetime import datetime, timezone

from PySide6.QtCore import QObject, Signal, Slot, QUrl
from PySide6.QtMultimedia import QCamera, QCameraDevice, QMediaCaptureSession, QMediaDevices, QMediaFormat, QMediaRecorder, QVideoSink

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
        is_recording = state == QMediaRecorder.RecorderState.RecordingState
        self._set_recording(is_recording)

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
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        filename = f"{name}_{timestamp}.mp4"
        return os.path.join(folder_path, filename)

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

            if not local_path or not os.path.isdir(local_path):
                self.errorOccurred.emit(
                    self._device_id, f"Invalid output folder: {folder_path}"
                )
                return

            output_path = self._generate_output_path(local_path)
            self._recorder.setOutputLocation(QUrl.fromLocalFile(output_path))
            self._recorder.record()
        except Exception as exc:
            self.errorOccurred.emit(self._device_id, f"Failed to start recording: {exc}")
            self._set_recording(False)

    # Stop the current recording
    @Slot(str)
    def stopRecording(self, device_id: str) -> None:
        if device_id != self._device_id:
            return
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
            self._set_recording(False)
        except Exception as exc:
            # Notify Capture Session Manager Thread of termination error
            self.errorOccurred.emit(self._device_id, str(exc))
        finally:
            # Notify Capture Session Manager Thread has stopped
            self.stopped.emit(self._device_id)
