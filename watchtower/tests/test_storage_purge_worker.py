from datetime import datetime, timezone
from pathlib import Path
from typing import List
from unittest.mock import MagicMock

import pytest

from backend.storage_purge_worker import (
    StoragePurgeWorker,
    _FILENAME_TIMESTAMP_RE,
    _parse_filename_timestamp,
)


@pytest.fixture
def mock_storage_info(monkeypatch):
    """Replace QStorageInfo so bytesAvailable returns a configurable value."""

    def _make(available_bytes: int):
        instance = MagicMock()
        instance.bytesAvailable.return_value = available_bytes

        class FakeStorageInfo:
            def __init__(self, *args, **kwargs):
                pass

            def bytesAvailable(self):
                return available_bytes

        monkeypatch.setattr(
            "backend.storage_purge_worker.QStorageInfo",
            FakeStorageInfo,
        )
        return available_bytes

    return _make


def test_parse_filename_timestamp_valid():
    dt = _parse_filename_timestamp("camera_20240115_143027_123.mp4")
    assert dt is not None
    assert dt.year == 2024
    assert dt.month == 1
    assert dt.day == 15
    assert dt.hour == 14
    assert dt.minute == 30
    assert dt.second == 27


def test_parse_filename_timestamp_invalid():
    assert _parse_filename_timestamp("not_a_recording.mp4") is None
    assert _parse_filename_timestamp("camera_20240115_143027.mp4") is None
    assert _parse_filename_timestamp("") is None


def test_filename_regex_matches_expected_pattern():
    assert _FILENAME_TIMESTAMP_RE.search("cam_20231201_120000_000.mp4")
    assert not _FILENAME_TIMESTAMP_RE.search("cam_20231201_120000.mp4")


def make_recording(folder: Path, name: str, content: bytes = b"x" * 100) -> Path:
    path = folder / name
    path.write_bytes(content)
    return path


def test_purge_empty_folder(mock_storage_info, temp_folder):
    mock_storage_info(10 * 1024 ** 3)
    worker = StoragePurgeWorker()
    deleted = worker._purge([str(temp_folder)], set(), 1024, 86400, str(temp_folder))
    assert deleted == []


def test_purge_deletes_files_past_retention(mock_storage_info, temp_folder):
    mock_storage_info(10 * 1024 ** 3)

    old_file = make_recording(temp_folder, "cam_20230101_120000_000.mp4")
    new_file = make_recording(temp_folder, "cam_20990101_120000_000.mp4")

    worker = StoragePurgeWorker()
    # 1 day retention; the old file is far older.
    deleted = worker._purge([str(temp_folder)], set(), 0, 86400, str(temp_folder))

    assert old_file in [Path(p) for p in deleted]
    assert new_file.exists()


def test_purge_keeps_protected_files(mock_storage_info, temp_folder):
    mock_storage_info(0)  # Force space-based deletion.

    old = make_recording(temp_folder, "cam_20230101_120000_000.mp4")
    newer = make_recording(temp_folder, "cam_20230102_120000_000.mp4")

    worker = StoragePurgeWorker()
    deleted = worker._purge([str(temp_folder)], {str(old)}, 10 * 1024 ** 3, 86400 * 365, str(temp_folder))

    assert str(old) not in deleted
    assert str(newer) in deleted


def test_purge_ignores_non_mp4(mock_storage_info, temp_folder):
    mock_storage_info(0)

    mp4 = make_recording(temp_folder, "cam_20230101_120000_000.mp4")
    txt = temp_folder / "notes.txt"
    txt.write_text("ignore me")

    worker = StoragePurgeWorker()
    deleted = worker._purge([str(temp_folder)], set(), 10 * 1024 ** 3, 86400 * 365, str(temp_folder))

    assert str(mp4) in deleted
    assert txt.exists()


def test_purge_deletes_oldest_first_until_space_target_met(mock_storage_info, temp_folder):
    # Available space is 500 bytes; target is 1000 bytes.
    mock_storage_info(500)

    oldest = make_recording(temp_folder, "cam_20230101_120000_000.mp4", b"o" * 300)
    middle = make_recording(temp_folder, "cam_20230102_120000_000.mp4", b"m" * 300)
    newest = make_recording(temp_folder, "cam_20230103_120000_000.mp4", b"n" * 300)

    worker = StoragePurgeWorker()
    deleted = worker._purge(
        [str(temp_folder)],
        set(),
        1000,
        86400 * 365 * 100,  # Far future retention so age does not trigger deletion.
        str(temp_folder),
    )

    deleted_paths = [Path(p) for p in deleted]
    assert oldest in deleted_paths
    assert middle in deleted_paths
    assert newest.exists()  # Not needed once free space target is reached.


def test_purge_skips_missing_folder(mock_storage_info, temp_folder):
    mock_storage_info(10 * 1024 ** 3)
    worker = StoragePurgeWorker()
    deleted = worker._purge([str(temp_folder / "does-not-exist")], set(), 0, 86400, str(temp_folder))
    assert deleted == []


def test_perform_purge_emits_purged_files(qtbot, mock_storage_info, temp_folder):
    mock_storage_info(10 * 1024 ** 3)
    old_file = make_recording(temp_folder, "cam_20230101_120000_000.mp4")

    worker = StoragePurgeWorker()
    with qtbot.waitSignal(worker.purgedFiles, timeout=1000):
        worker.performPurge(
            active_folders=[str(temp_folder)],
            protected_files=set(),
            folders_to_scan=[str(temp_folder)],
            purge_active_only=True,
            min_free_bytes=0,
            max_retention_seconds=86400,
            root_path=str(temp_folder),
        )

    assert not old_file.exists()
