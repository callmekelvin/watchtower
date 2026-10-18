from typing import Dict

from PySide6.QtCore import QObject, QThread, Signal, Slot, Property, QMetaObject, Qt
from PySide6.QtMultimedia import QVideoSink

from backend.device_manager import DeviceManager
from backend.capture_session_worker import CaptureSessionWorker

# CaptureSessionManager - Manages CaptureSessionWorker Threads, which perform multimedia processing
class CaptureSessionManager(QObject):
    # Emit Signals to indicate change in Camera/ Selected Camera and Capture Session Worker (Arg: Device ID)
    currentDeviceIdChanged = Signal()
    cameraActiveChanged = Signal()
    errorOccurred = Signal(str)
    sessionStarted = Signal(str)
    sessionStopped = Signal(str)

    # Internal signal used to deliver the video sink to workers on their own threads.
    _videoSinkRequested = Signal(QVideoSink)

    def __init__(self, device_manager: DeviceManager, parent: QObject | None = None):
        super().__init__(parent)
        self._device_manager = device_manager

        # Store Capture Session Workers/ Threads - { Key: DeviceID, Value: SessionWorker/ Thread }
        self._workers: Dict[str, CaptureSessionWorker] = {}
        self._threads: Dict[str, QThread] = {}
        self._current_device_id: str = ""
        self._camera_active: bool = False
        self._video_sink: QVideoSink | None = None

    # Property - Listens and return Current Camera Device ID
    @Property(str, notify=currentDeviceIdChanged)
    def currentDeviceId(self) -> str:
        return self._current_device_id

    # Property - Listens and return if current Camera Session is Active
    @Property(bool, notify=cameraActiveChanged)
    def cameraActive(self) -> bool:
        return self._camera_active

    @Slot(QVideoSink)
    def setVideoSink(self, sink: QVideoSink) -> None:
        # Store the sink so that future workers pick it up automatically.
        self._video_sink = sink
        self._videoSinkRequested.emit(sink)

    # Temporary Function - For Current Scenario where we stop the Current Capture Session Worker Session/ Thread before starting a new one
    @Slot(str)
    def setCameraById(self, device_id: str) -> None:
        if not device_id:
            self.stopCurrentSession()
            return

        if device_id == self._current_device_id:
            self._restart_current_session(device_id)
            return

        self._stop_current_session()
        self._start_session(device_id)

    # Stop Current Capture Session Worker/ Thread
    @Slot()
    def stopCurrentSession(self) -> None:
        self._stop_current_session()

    # Stop all Capture Session Workers/ Threads
    @Slot()
    def stopAll(self) -> None:
        for device_id in list(self._workers.keys()):
            self._stop_session(device_id)
        self._set_current_device_id("")
        self._set_camera_active(False)

    # Terminate all ongoing Capture Session/ Thread on Program Exit
    def shutdown(self) -> None:
        self.stopAll()

    # Start Capture Session Worker/ Thread
    def _start_session(self, device_id: str) -> None:
        thread = QThread(self)
        worker = CaptureSessionWorker(device_id)

        # Route sink changes to the worker thread.
        self._videoSinkRequested.connect(worker.setVideoSink)

        # Move QT Worker Object into Thread
        worker.moveToThread(thread)

        # Track this Capture Worker/ Thread
        self._workers[device_id] = worker
        self._threads[device_id] = thread

        # Wire cleanup signals to thread
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(lambda: self._cleanup_thread(device_id))

        # Wire worker signals back to manager with Qt.QueuedConnection so they execute on the GUI threa
        worker.sessionReady.connect(self._on_session_ready, Qt.QueuedConnection)
        worker.errorOccurred.connect(self._on_worker_error, Qt.QueuedConnection)
        worker.stopped.connect(self._on_worker_stopped, Qt.QueuedConnection)

        # Start Thread/ Worker
        thread.started.connect(worker.initializeAndStart)
        thread.start()

        # Prime the worker with the current sink after the thread has started.
        if self._video_sink is not None:
            self._videoSinkRequested.emit(self._video_sink)

        self._set_current_device_id(device_id)
        self._set_camera_active(True)

    def _restart_current_session(self, device_id: str) -> None:
        self._stop_session(device_id)
        self._set_current_device_id("")
        self._set_camera_active(False)
        self._start_session(device_id)

    def _stop_current_session(self) -> None:
        if self._current_device_id:
            self._stop_session(self._current_device_id)
        self._set_current_device_id("")
        self._set_camera_active(False)

    def _stop_session(self, device_id: str) -> None:
        # Retrieve/ remove capture session from Worker/ Thread Dictionaries
        worker = self._workers.pop(device_id, None)
        thread = self._threads.pop(device_id, None)

        if worker is None or thread is None:
            return

        try:
            # Safetly Stop Worker Thread - Invoke Stop Method within Capture Session Worker
            QMetaObject.invokeMethod(worker, "stop", Qt.QueuedConnection)
            thread.quit()

            # Give it 3 seconds for Thread to Finish
            if not thread.wait(3000):
                thread.terminate()
                thread.wait()
        except Exception:
            pass
        finally:
            # Forceful Thread Termination
            thread.deleteLater()

    def _cleanup_thread(self, device_id: str) -> None:
        self._workers.pop(device_id, None)
        self._threads.pop(device_id, None)

    # Worker Signal Functions
    def _on_session_ready(self, device_id: str, _session: QObject) -> None:
        # The session object is owned by the worker thread; QML uses the video sink.
        self.sessionStarted.emit(device_id)

    def _on_worker_error(self, device_id: str, message: str) -> None:
        self.errorOccurred.emit(message)
        self._stop_session(device_id)
        if self._current_device_id == device_id:
            self._set_current_device_id("")
            self._set_camera_active(False)

    def _on_worker_stopped(self, device_id: str) -> None:
        if self._current_device_id == device_id:
            self._set_current_device_id("")
            self._set_camera_active(False)
        self.sessionStopped.emit(device_id)

    def _set_current_device_id(self, device_id: str) -> None:
        if self._current_device_id == device_id:
            return
        self._current_device_id = device_id
        self.currentDeviceIdChanged.emit()

    def _set_camera_active(self, active: bool) -> None:
        if self._camera_active == active:
            return
        self._camera_active = active
        self.cameraActiveChanged.emit()
