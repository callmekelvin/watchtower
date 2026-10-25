from typing import Dict, Optional, Set

from PySide6.QtCore import QObject, QThread, Signal, Slot, Property, QMetaObject, Qt, QUrl
from PySide6.QtMultimedia import QVideoSink

from backend.device_manager import DeviceManager
from backend.capture_session_worker import CaptureSessionWorker

# Avoid a runtime import cycle - StorageManager is only used for type hints.
StorageManager = "StorageManager"


# CaptureSessionManager - Manages CaptureSessionWorker Threads, which perform multimedia processing
class CaptureSessionManager(QObject):
    # Emit Signals to indicate change in Camera/ Selected Camera and Capture Session Worker (Arg: Device ID)
    currentDeviceIdChanged = Signal()
    cameraActiveChanged = Signal()
    errorOccurred = Signal(str)
    sessionStarted = Signal(str)
    sessionStopped = Signal(str)

    # Emitted when a worker's recording state changes (Arg: device_id, is_recording)
    deviceRecordingStateChanged = Signal(str, bool)

    # Emitted when a segment file has been finalized (Arg: device_id, finalized_file_path)
    segmentFinalized = Signal(str, str)

    # Internal signals used to deliver sink changes to workers on their own threads - Emit to all Camera Threads (Arg: device_id, Sink)
    _setWorkerVideoSink = Signal(str, QVideoSink)
    _clearWorkerVideoSink = Signal(str)

    # Internal signals used to deliver recording commands to workers on their own threads. (Arg: device_id, Folder Path)
    _startRecordingForWorker = Signal(str, str)
    _stopRecordingForWorker = Signal(str)

    def __init__(self, device_manager: DeviceManager, storage_manager: Optional[StorageManager] = None, parent: QObject | None = None):
        super().__init__(parent)
        self._device_manager = device_manager
        self._storage_manager: Optional[StorageManager] = storage_manager

        # Store Capture Session Workers/ Threads/ Sinks - { Key: DeviceID, Value: ... }
        self._workers: Dict[str, CaptureSessionWorker] = {}
        self._threads: Dict[str, QThread] = {}
        self._sinks: Dict[str, QVideoSink] = {}
        self._recording_states: Dict[str, bool] = {}
        self._current_device_id: str = ""
        self._camera_active: bool = False

        # Active output folders and currently-writing segment files per device.
        self._recording_folders: Dict[str, str] = {}
        self._active_files: Dict[str, str] = {}

        # Set when storage is critical so no new segments are started.
        self._critical_stop_active: bool = False

        # Connect storage manager signals.
        if self._storage_manager is not None:
            self._storage_manager.storageCritical.connect(self._on_storage_critical)

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

    # Start recording the specified device to the given folder.
    @Slot(str, str)
    def startRecordingForDevice(self, device_id: str, folder_path: str) -> None:
        if not device_id:
            return

        # Normalize the folder path once on the manager thread so the
        # tracked active folder matches the path the worker will use.
        url = QUrl(folder_path)
        local_path = url.toLocalFile() if url.isLocalFile() else folder_path
        if not local_path:
            self.errorOccurred.emit(f"Invalid output folder: {folder_path}")
            return

        # Check if there is sufficient space to begin recording
        if self._storage_manager is not None:
            free_gb = self._storage_manager.free_space_gb_for_path(local_path)
            min_free_gb = self._storage_manager.minFreeSpaceGb
            if free_gb < min_free_gb:
                self.errorOccurred.emit(f"Insufficient free space ({free_gb:.2f} GB). Recording requires at least {min_free_gb} GB.")
                return

        # There is sufficient space/ space has been made available since last check
        self._critical_stop_active = False

        if self._storage_manager is not None:
            self._storage_manager.addManagedFolder(local_path)

        if device_id in self._workers:
            self._recording_folders[device_id] = local_path
            self._update_storage_manager()
            self._startRecordingForWorker.emit(device_id, folder_path)

    # Stop recording the specified device.
    @Slot(str)
    def stopRecordingForDevice(self, device_id: str) -> None:
        if not device_id:
            return
        if device_id in self._workers:
            self._stopRecordingForWorker.emit(device_id)

    # Query whether a given device is currently recording.
    @Slot(str, result=bool)
    def isDeviceRecording(self, device_id: str) -> bool:
        return self._recording_states.get(device_id, False)

    # Terminate all ongoing Capture Session/ Thread on Program Exit
    def shutdown(self) -> None:
        self.stopAll()

    # React to a critical storage situation by stopping all recording
    def _on_storage_critical(self, reason: str) -> None:
        self._critical_stop_active = True
        for device_id in list(self._recording_states.keys()):
            if self._recording_states.get(device_id, False):
                self.stopRecordingForDevice(device_id)

    # Push the current active folders/files to the storage manager
    def _update_storage_manager(self) -> None:
        if self._storage_manager is None:
            return
        folders: Set[str] = set(self._recording_folders.values())
        protected: Set[str] = set(self._active_files.values())
        self._storage_manager.updateActiveFolders(list(folders), protected)

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

        # Wire recording command signals to the worker.
        self._startRecordingForWorker.connect(worker.startRecording)
        self._stopRecordingForWorker.connect(worker.stopRecording)
        worker.recordingStateChanged.connect(self._on_worker_recording_state_changed)
        worker.segmentStarted.connect(self._on_segment_started, Qt.QueuedConnection)
        worker.segmentFinalized.connect(self._on_segment_finalized, Qt.QueuedConnection)

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

        self._recording_folders.pop(device_id, None)
        self._active_files.pop(device_id, None)
        self._update_storage_manager()

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
        self._recording_folders.pop(device_id, None)
        self._active_files.pop(device_id, None)
        self._update_storage_manager()

    # Worker Signal Functions
    def _on_session_ready(self, device_id: str, _session: QObject) -> None:
        # The session object is owned by the worker thread; QML uses the video sink.
        self._recording_states[device_id] = False
        self.sessionStarted.emit(device_id)

    def _on_worker_error(self, device_id: str, message: str) -> None:
        # Workers stay alive until application shutdown
        self.errorOccurred.emit(message)

    def _on_worker_stopped(self, device_id: str) -> None:
        if self._current_device_id == device_id:
            self._set_current_device_id("")
            self._set_camera_active(False)
        self._recording_states.pop(device_id, None)
        self._recording_folders.pop(device_id, None)
        self._active_files.pop(device_id, None)
        self._update_storage_manager()
        self.sessionStopped.emit(device_id)

    def _on_worker_recording_state_changed(self, device_id: str, is_recording: bool) -> None:
        self._recording_states[device_id] = is_recording
        if not is_recording:
            self._recording_folders.pop(device_id, None)
            self._active_files.pop(device_id, None)
        self._update_storage_manager()
        self.deviceRecordingStateChanged.emit(device_id, is_recording)

    def _on_segment_started(self, device_id: str, file_path: str) -> None:
        self._active_files[device_id] = file_path
        self._update_storage_manager()

    def _on_segment_finalized(self, device_id: str, file_path: str) -> None:
        self.segmentFinalized.emit(device_id, file_path)
        self._update_storage_manager()

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
