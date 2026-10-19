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

    # Internal signals used to deliver sink changes to workers on their own threads - Emit to all Camera Threads
    _setWorkerVideoSink = Signal(str, QVideoSink)
    _clearWorkerVideoSink = Signal(str)

    def __init__(self, device_manager: DeviceManager, parent: QObject | None = None):
        super().__init__(parent)
        self._device_manager = device_manager

        # Store Capture Session Workers/ Threads/ Sinks - { Key: DeviceID, Value: ... }
        self._workers: Dict[str, CaptureSessionWorker] = {}
        self._threads: Dict[str, QThread] = {}
        self._sinks: Dict[str, QVideoSink] = {}
        self._current_device_id: str = ""
        self._camera_active: bool = False

        # Start a capture worker for every camera that the device manager detects.
        self._device_manager.videoInputsChanged.connect(self._on_video_inputs_changed)

    # Property - Listens and return Current Camera Device ID
    @Property(str, notify=currentDeviceIdChanged)
    def currentDeviceId(self) -> str:
        return self._current_device_id

    # Property - Listens and return if current Camera Session is Active
    @Property(bool, notify=cameraActiveChanged)
    def cameraActive(self) -> bool:
        return self._camera_active

    # Function - Register the QVideoSink for a specific camera. The sink is created by QML's VideoOutput
    @Slot(str, QVideoSink)
    def setVideoSinkForDevice(self, device_id: str, sink: QVideoSink) -> None:
        if not device_id or sink is None:
            return
        self._sinks[device_id] = sink
        if device_id in self._workers:
            self._setWorkerVideoSink.emit(device_id, sink)

    # Function - Unregister the QVideoSink for a specific camera
    @Slot(str)
    def clearVideoSinkForDevice(self, device_id: str) -> None:
        if not device_id:
            return
        self._sinks.pop(device_id, None)
        if device_id in self._workers:
            self._clearWorkerVideoSink.emit(device_id)

    # Select which camera's feed is shown on the QML video output.
    # The worker thread for the selected camera is not started or stopped here.
    @Slot(str)
    def setCameraById(self, device_id: str) -> None:
        if device_id == self._current_device_id:
            return
        self._set_current_device_id(device_id)
        self._set_camera_active(bool(device_id))

    # Stop displaying the current camera - The underlying worker thread keeps running.
    @Slot()
    def stopCurrentSession(self) -> None:
        self.setCameraById("")

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

    # Start a worker for every newly detected camera.
    def _on_video_inputs_changed(self) -> None:
        for device in self._device_manager.video_inputs():
            device_id = device.device_id
            if device_id not in self._workers:
                self._start_session(device_id)

    # Start Capture Session Worker/ Thread
    def _start_session(self, device_id: str) -> None:
        thread = QThread(self)
        worker = CaptureSessionWorker(device_id)

        # Move QT Worker Object into Thread
        worker.moveToThread(thread)

        # Track this Capture Worker/ Thread
        self._workers[device_id] = worker
        self._threads[device_id] = thread

        # Connect sink-delivery signals before the thread starts so queued emissions work.
        self._setWorkerVideoSink.connect(worker.setVideoSink)
        self._clearWorkerVideoSink.connect(worker.clearVideoSink)

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

        # If a sink was already registered for this device, send it to the worker now/ again
        if device_id in self._sinks:
            self._setWorkerVideoSink.emit(device_id, self._sinks[device_id])

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
        # Workers stay alive until application shutdown
        self.errorOccurred.emit(message)

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
