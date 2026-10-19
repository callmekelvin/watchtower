from PySide6.QtCore import QObject, Signal, Slot
from PySide6.QtMultimedia import QCamera, QMediaCaptureSession, QMediaDevices, QMediaRecorder, QVideoSink

from backend.device_worker import _decode_id

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

    def __init__(self, device_id: str, parent: QObject | None = None):
        super().__init__(parent)
        self._device_id = device_id
        self._session: QMediaCaptureSession | None = None
        self._camera: QCamera | None = None
        self._recorder: QMediaRecorder | None = None
        self._media_devices: QMediaDevices | None = None
        self._video_sink: QVideoSink | None = None

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
            camera_device = None
            for device in self._media_devices.videoInputs():
                if _decode_id(device.id()) == self._device_id:
                    camera_device = device
                    break

            # Emit error if No Camera is found
            if camera_device is None:
                self.errorOccurred.emit(
                    self._device_id, f"Camera '{self._device_id}' not found"
                )
                return

            # Create QCamera Object using QCameraDevice
            self._camera = QCamera(camera_device, self)
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

    # Function called by Capture Session Manager when Capture Session Worker Thread is to be stopped/ terminated
    @Slot()
    def stop(self) -> None:
        # Clear Camera, Session and Recorder
        try:
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
        except Exception as exc:
            # Notify Capture Session Manager Thread of termination error
            self.errorOccurred.emit(self._device_id, str(exc))
        finally:
            # Notify Capture Session Manager Thread has stopped
            self.stopped.emit(self._device_id)
