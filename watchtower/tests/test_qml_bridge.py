from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest
from PySide6.QtCore import QObject, Signal

from backend.qml_bridge import QmlBridge, _device_to_dict

from tests.test_capture_session_manager import FakeDeviceManager


def test_device_to_dict():
    device = MagicMock()
    device.device_id = "cam-1"
    device.description = "Camera 1"
    device.is_default = True
    device.photo_resolutions = ["1920x1080"]
    fmt = MagicMock()
    fmt.resolution = "1920x1080"
    fmt.width = 1920
    fmt.height = 1080
    fmt.min_frame_rate = 15.0
    fmt.max_frame_rate = 30.0
    fmt.pixel_format = "Format_YUV420P"
    device.video_formats = [fmt]

    data = _device_to_dict(device)
    assert data["deviceId"] == "cam-1"
    assert data["description"] == "Camera 1"
    assert data["isDefault"] is True
    assert len(data["videoFormats"]) == 1
    assert data["videoFormats"][0]["width"] == 1920


class FakeCaptureManager(QObject):
    currentDeviceIdChanged = Signal()
    cameraActiveChanged = Signal()
    errorOccurred = Signal(str)
    fatalErrorOccurred = Signal(str)
    sessionStarted = Signal(str)
    sessionStopped = Signal(str)
    deviceRecordingStateChanged = Signal(str, bool)
    segmentFinalized = Signal(str, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._current_device_id = ""

    @property
    def currentDeviceId(self):
        return self._current_device_id

    def setCameraById(self, device_id):
        self._current_device_id = device_id
        self.currentDeviceIdChanged.emit()


class FakeStorageManager(QObject):
    policyChanged = Signal()
    storageStatusChanged = Signal()
    storageCritical = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)

    @property
    def minFreeSpaceGb(self):
        return 10

    @property
    def maxRetentionDays(self):
        return 30

    @property
    def checkIntervalMinutes(self):
        return 5

    @property
    def purgeActiveOnly(self):
        return False

    @property
    def managedFolders(self):
        return ["/tmp/a"]

    @property
    def storageStatusText(self):
        return "10.00 GB free"

    @property
    def storageUsageRatio(self):
        return 0.5

    def saveStoragePolicy(self, *args):
        self.policyChanged.emit()

    def loadStoragePolicy(self):
        self.policyChanged.emit()

    def triggerPurgeNow(self):
        pass

    def setPurgeActiveOnly(self, value):
        self.policyChanged.emit()

    def addManagedFolder(self, path):
        self.policyChanged.emit()

    def removeManagedFolder(self, path):
        self.policyChanged.emit()

    def clearManagedFolders(self):
        self.policyChanged.emit()


@pytest.fixture
def bridge(qtbot):
    device_mgr = FakeDeviceManager()
    capture_mgr = FakeCaptureManager()
    storage_mgr = FakeStorageManager()
    return QmlBridge(device_mgr, capture_mgr, storage_mgr)


def test_video_inputs_returns_dict_list(bridge):
    device = MagicMock()
    device.device_id = "cam-1"
    device.description = "Cam 1"
    device.is_default = False
    device.photo_resolutions = []
    device.video_formats = []
    bridge._device_manager._devices = [device]

    result = bridge.videoInputs
    assert isinstance(result, list)
    assert result[0]["deviceId"] == "cam-1"


def test_last_refresh_time_not_refreshed(bridge):
    assert bridge.lastRefreshTime == "Not Refreshed"


def test_last_refresh_time_format(bridge):
    now = datetime.now(timezone.utc)
    bridge._device_manager._last_refresh_time = now
    assert bridge.lastRefreshTime == now.isoformat()


def test_storage_properties_delegate(bridge):
    assert bridge.minFreeSpaceGb == 10
    assert bridge.maxRetentionDays == 30
    assert bridge.checkIntervalMinutes == 5
    assert bridge.purgeActiveOnly is False
    assert bridge.managedFolders == ["/tmp/a"]
    assert bridge.storageStatusText == "10.00 GB free"
    assert bridge.storageUsageRatio == 0.5


def test_save_storage_policy_delegates(qtbot, bridge):
    with qtbot.waitSignal(bridge.storagePolicyChanged, timeout=1000):
        bridge.saveStoragePolicy(20, 60, 10)


def test_load_storage_policy_delegates(qtbot, bridge):
    with qtbot.waitSignal(bridge.storagePolicyChanged, timeout=1000):
        bridge.loadStoragePolicy()


def test_refresh_devices_delegates(bridge):
    bridge._device_manager.refresh = MagicMock()
    bridge.refreshDevices()
    bridge._device_manager.refresh.assert_called_once()
