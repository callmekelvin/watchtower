from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

from backend.device_manager import DeviceManager
from backend.models import MediaDevice


@pytest.fixture
def manager(qtbot):
    """Create a DeviceManager and ensure its thread is shut down after the test."""
    mgr = DeviceManager()
    yield mgr
    mgr.shutdown()


def test_video_inputs_returns_cached_devices(manager):
    device = MediaDevice(device_id="cam-1", description="Camera 1", is_default=False)
    manager._on_devices_changed([device], datetime.now(timezone.utc))

    result = manager.video_inputs()
    assert len(result) == 1
    assert result[0].device_id == "cam-1"


def test_on_devices_changed_updates_timestamp_and_emits_signals(qtbot, manager):
    now = datetime.now(timezone.utc)
    device = MediaDevice(device_id="cam-2", description="Camera 2", is_default=True)

    with qtbot.waitSignals([manager.lastRefreshTimeChanged, manager.videoInputsChanged], timeout=1000):
        manager._on_devices_changed([device], now)

    assert manager.last_refresh_time() == now


def test_shutdown_quits_thread(manager):
    assert manager._thread.isRunning()
    manager.shutdown()
    assert not manager._thread.isRunning()
