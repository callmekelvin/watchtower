from unittest.mock import MagicMock

import pytest

from backend.storage_manager import StorageManager


@pytest.fixture
def mock_storage_info(monkeypatch):
    """Provide a fake QStorageInfo that reports fixed disk sizes."""

    def _make(available: int, total: int):
        class FakeStorageInfo:
            def __init__(self, *args, **kwargs):
                pass

            def bytesAvailable(self):
                return available

            def bytesTotal(self):
                return total

        monkeypatch.setattr("backend.storage_manager.QStorageInfo", FakeStorageInfo)
        return FakeStorageInfo

    return _make


@pytest.fixture
def storage_manager(qtbot, ini_settings, mock_storage_info, monkeypatch):
    """Create a StorageManager with isolated INI settings and mocked storage info."""
    mock_storage_info(100 * 1024 ** 3, 500 * 1024 ** 3)

    # Force StorageManager to use the isolated INI settings.
    monkeypatch.setattr(
        "backend.storage_manager.QSettings",
        lambda *args, **kwargs: ini_settings,
    )

    mgr = StorageManager()
    yield mgr
    mgr.shutdown()


def test_policy_save_and_load_round_trip(storage_manager):
    storage_manager.saveStoragePolicy(10, 60, 15)
    storage_manager._min_free_space_gb = 0
    storage_manager._max_retention_days = 0
    storage_manager._check_interval_minutes = 0

    storage_manager.loadStoragePolicy()

    assert storage_manager.minFreeSpaceGb == 10
    assert storage_manager.maxRetentionDays == 60
    assert storage_manager.checkIntervalMinutes == 15


def test_save_policy_clamps_invalid_values(storage_manager):
    storage_manager.saveStoragePolicy(-5, 0, 0)
    assert storage_manager.minFreeSpaceGb == 0
    assert storage_manager.maxRetentionDays == 1
    assert storage_manager.checkIntervalMinutes == 1


def test_managed_folders_add_remove_clear(storage_manager, temp_folder):
    folder = str(temp_folder / "watchtower" / "recordings")
    storage_manager.addManagedFolder(folder)
    assert folder in storage_manager.managedFolders

    storage_manager.removeManagedFolder(folder)
    assert folder not in storage_manager.managedFolders

    storage_manager.addManagedFolder(folder)
    storage_manager.clearManagedFolders()
    assert storage_manager.managedFolders == []


def test_managed_folder_normalization_skips_empty(storage_manager):
    storage_manager.addManagedFolder("")
    assert storage_manager.managedFolders == []


def test_purge_active_only_returns_early_with_no_active_folders(storage_manager):
    storage_manager._purge_active_only = True
    storage_manager._active_folders = []
    storage_manager._dispatchPurge = MagicMock()

    storage_manager._on_purge_due()

    storage_manager._dispatchPurge.assert_not_called()


def test_purge_active_only_scans_active_folders(storage_manager):
    storage_manager._purge_active_only = True
    storage_manager._active_folders = ["/tmp/active"]
    storage_manager._managed_folders = {"/tmp/managed"}
    storage_manager._protected_files = set()
    storage_manager._dispatchPurge = MagicMock()

    storage_manager._on_purge_due()

    args = storage_manager._dispatchPurge.emit.call_args[0]
    assert args[2] == ["/tmp/active"]


def test_purge_scans_union_when_active_only_false(storage_manager):
    storage_manager._purge_active_only = False
    storage_manager._active_folders = ["/tmp/active"]
    storage_manager._managed_folders = {"/tmp/managed"}
    storage_manager._protected_files = set()
    storage_manager._dispatchPurge = MagicMock()

    storage_manager._on_purge_due()

    args = storage_manager._dispatchPurge.emit.call_args[0]
    assert set(args[2]) == {"/tmp/active", "/tmp/managed"}


def test_on_purge_due_returns_early_when_no_folders_to_scan(storage_manager):
    storage_manager._purge_active_only = False
    storage_manager._active_folders = []
    storage_manager._managed_folders = set()
    storage_manager._dispatchPurge = MagicMock()

    storage_manager._on_purge_due()

    storage_manager._dispatchPurge.assert_not_called()


def test_on_purge_due_emits_min_free_bytes_without_overflow(storage_manager):
    """Large min-free-space values must survive the cross-thread signal as qint64."""
    storage_manager._min_free_space_gb = 5
    storage_manager._max_retention_days = 30
    storage_manager._purge_active_only = True
    storage_manager._active_folders = ["/tmp/active"]
    storage_manager._protected_files = set()
    storage_manager._dispatchPurge = MagicMock()

    storage_manager._on_purge_due()

    args = storage_manager._dispatchPurge.emit.call_args[0]
    assert args[4] == 5 * 1024 ** 3  # min_free_bytes
    assert args[5] == 30 * 24 * 60 * 60  # max_retention_seconds


def test_update_active_folders(storage_manager):
    storage_manager.updateActiveFolders(["/tmp/folder"], {"/tmp/folder/file.mp4"})
    assert storage_manager._active_folders == ["/tmp/folder"]
    assert storage_manager._protected_files == {"/tmp/folder/file.mp4"}


def test_status_root_path_prefers_active_then_managed(storage_manager, temp_folder):
    active = temp_folder / "active"
    managed = temp_folder / "managed"
    active.mkdir()
    managed.mkdir()

    storage_manager._active_folders = [str(active)]
    storage_manager._managed_folders = {str(managed)}

    assert storage_manager._status_root_path() == str(active)

    storage_manager._active_folders = []
    assert storage_manager._status_root_path() == str(managed)


def test_free_space_gb_for_path_delegates(storage_manager):
    # With the mock, free space is fixed at 100 GB.
    assert storage_manager.free_space_gb_for_path("/any/path") == 100.0


def test_storage_status_text_format(storage_manager):
    text = storage_manager.storageStatusText
    assert "GB free of" in text
    assert "GB used" in text
    assert "%" in text


def test_on_purged_files_emits_critical_when_still_low_space(storage_manager, qtbot, monkeypatch):
    # Pretend free space is below the minimum after purging.
    storage_manager._min_free_space_gb = 100
    storage_manager._free_space_gb = lambda _path: 50.0

    with qtbot.waitSignal(storage_manager.storageCritical, timeout=1000) as blocker:
        storage_manager._on_purged_files(["/tmp/old.mp4"])
    assert "Free space" in blocker.args[0]


def test_on_purge_failed_emits_critical(storage_manager, qtbot):
    with qtbot.waitSignal(storage_manager.storageCritical, timeout=1000) as blocker:
        storage_manager._on_purge_failed("disk not responding")
    assert "Purge failed" in blocker.args[0]


def test_set_purge_active_only_persists(storage_manager):
    storage_manager.setPurgeActiveOnly(True)
    assert storage_manager.purgeActiveOnly is True

    storage_manager.setPurgeActiveOnly(False)
    assert storage_manager.purgeActiveOnly is False
