from unittest.mock import MagicMock, patch

import pytest

from backend.nas_connection import NasConnection
from backend.nas_manager import NasManager


@pytest.fixture
def nas_manager(qtbot, ini_settings, monkeypatch, tmp_path):
    """Create a NasManager with isolated INI-backed settings."""
    monkeypatch.setattr(
        "backend.nas_manager.QSettings",
        lambda *args, **kwargs: ini_settings,
    )
    mgr = NasManager()
    yield mgr


def test_save_connection_adds_and_persists(nas_manager, qtbot):
    with qtbot.waitSignal(nas_manager.connectionStatusChanged):
        nas_manager.saveConnection({
            "name": "Home NAS",
            "protocol": "smb",
            "host": "nas",
            "share": "recordings",
            "username": "user",
        })

    assert len(nas_manager.connections) == 1
    assert nas_manager.connections[0]["name"] == "Home NAS"
    assert nas_manager.connections[0]["protocol"] == "smb"


def test_save_connection_invalid_data_emits_error(nas_manager, qtbot):
    with qtbot.waitSignal(nas_manager.errorOccurred):
        nas_manager.saveConnection({
            "name": "",
            "protocol": "smb",
            "host": "nas",
            "share": "recordings",
        })


def test_delete_connection_removes_entry(nas_manager):
    nas_manager.saveConnection({
        "name": "Home NAS",
        "protocol": "smb",
        "host": "nas",
        "share": "recordings",
    })
    conn_id = nas_manager.connections[0]["id"]
    nas_manager.deleteConnection(conn_id)
    assert nas_manager.connections == []


def test_request_connect_prompts_for_password(nas_manager, qtbot):
    nas_manager.saveConnection({
        "name": "Home NAS",
        "protocol": "smb",
        "host": "nas",
        "share": "recordings",
        "username": "user",
    })
    conn_id = nas_manager.connections[0]["id"]

    with qtbot.waitSignal(nas_manager.passwordPromptRequested) as blocker:
        nas_manager.requestConnect(conn_id)

    assert blocker.args[0] == conn_id
    assert "Home NAS" in blocker.args[1]


def test_submit_password_mounts_and_emits_status(nas_manager, qtbot, monkeypatch, tmp_path):
    nas_manager.saveConnection({
        "name": "Home NAS",
        "protocol": "smb",
        "host": "nas",
        "share": "recordings",
        "username": "user",
    })
    conn_id = nas_manager.connections[0]["id"]

    def fake_mount(conn, mount_point, password, drive_letter):
        mount_point.mkdir(parents=True, exist_ok=True)
        return True, None, None

    monkeypatch.setattr("backend.nas_manager.mount_share", fake_mount)

    nas_manager.requestConnect(conn_id)
    with qtbot.waitSignal(nas_manager.connectionStatusChanged):
        nas_manager.submitPassword(conn_id, "secret")

    assert nas_manager.isConnectionMounted(conn_id) is True
    assert nas_manager.statusForConnection(conn_id) == "connected"


def test_submit_password_mount_failure_emits_error(nas_manager, qtbot, monkeypatch):
    nas_manager.saveConnection({
        "name": "Home NAS",
        "protocol": "smb",
        "host": "nas",
        "share": "recordings",
    })
    conn_id = nas_manager.connections[0]["id"]

    monkeypatch.setattr(
        "backend.nas_manager.mount_share",
        lambda *args, **kwargs: (False, None, "Permission denied"),
    )

    nas_manager.requestConnect(conn_id)
    with qtbot.waitSignal(nas_manager.errorOccurred) as blocker:
        nas_manager.submitPassword(conn_id, "secret")

    assert "Permission denied" in blocker.args[0]
    assert nas_manager.isConnectionMounted(conn_id) is False


def test_request_disconnect_blocked_when_recording(nas_manager, qtbot):
    nas_manager.saveConnection({
        "name": "Home NAS",
        "protocol": "smb",
        "host": "nas",
        "share": "recordings",
    })
    conn_id = nas_manager.connections[0]["id"]
    nas_manager.setNasRecordingActive("cam-1", conn_id, True)

    with qtbot.waitSignal(nas_manager.errorOccurred) as blocker:
        nas_manager.requestDisconnect(conn_id)

    assert "recording is in progress" in blocker.args[0]


def test_mount_for_recording_emits_path_when_mounted(nas_manager, qtbot, monkeypatch, tmp_path):
    nas_manager.saveConnection({
        "name": "Home NAS",
        "protocol": "smb",
        "host": "nas",
        "share": "recordings",
    })
    conn_id = nas_manager.connections[0]["id"]

    def fake_mount(conn, mount_point, password, drive_letter):
        mount_point.mkdir(parents=True, exist_ok=True)
        return True, None, None

    monkeypatch.setattr("backend.nas_manager.mount_share", fake_mount)

    nas_manager.requestConnect(conn_id)
    nas_manager.submitPassword(conn_id, "secret")

    with qtbot.waitSignal(nas_manager.recordingPathReady) as blocker:
        nas_manager.mountForRecording(conn_id, "cam-1")

    assert blocker.args[0] == "cam-1"
    assert "cam_1" in blocker.args[1] or "cam-1" in blocker.args[1]


def test_mount_for_recording_prompts_password_when_not_mounted(nas_manager, qtbot):
    nas_manager.saveConnection({
        "name": "Home NAS",
        "protocol": "smb",
        "host": "nas",
        "share": "recordings",
    })
    conn_id = nas_manager.connections[0]["id"]

    with qtbot.waitSignal(nas_manager.passwordPromptRequested) as blocker:
        nas_manager.mountForRecording(conn_id, "cam-1")

    assert blocker.args[0] == conn_id


def test_any_nas_recording_active_property(nas_manager, qtbot):
    nas_manager.saveConnection({
        "name": "Home NAS",
        "protocol": "smb",
        "host": "nas",
        "share": "recordings",
    })
    conn_id = nas_manager.connections[0]["id"]

    with qtbot.waitSignal(nas_manager.anyNasRecordingActiveChanged):
        nas_manager.setNasRecordingActive("cam-1", conn_id, True)
    assert nas_manager.anyNasRecordingActive is True

    with qtbot.waitSignal(nas_manager.anyNasRecordingActiveChanged):
        nas_manager.setNasRecordingActive("cam-1", conn_id, False)
    assert nas_manager.anyNasRecordingActive is False


def test_connection_persistence_across_instances(nas_manager, ini_settings, monkeypatch):
    nas_manager.saveConnection({
        "name": "Persisted NAS",
        "protocol": "nfs",
        "host": "nas",
        "share": "export",
    })

    monkeypatch.setattr(
        "backend.nas_manager.QSettings",
        lambda *args, **kwargs: ini_settings,
    )
    new_manager = NasManager()
    assert len(new_manager.connections) == 1
    assert new_manager.connections[0]["name"] == "Persisted NAS"


def test_request_connect_unknown_connection_emits_error(nas_manager, qtbot):
    with qtbot.waitSignal(nas_manager.errorOccurred) as blocker:
        nas_manager.requestConnect("does-not-exist")
    assert "Unknown NAS connection" in blocker.args[0]


def test_request_connect_nfs_does_not_prompt_for_password(nas_manager, qtbot, monkeypatch):
    nas_manager.saveConnection({
        "name": "NFS NAS",
        "protocol": "nfs",
        "host": "nas",
        "share": "export",
    })
    conn_id = nas_manager.connections[0]["id"]

    def fake_mount(conn, mount_point, password, drive_letter):
        mount_point.mkdir(parents=True, exist_ok=True)
        return True, None, None

    monkeypatch.setattr("backend.nas_manager.mount_share", fake_mount)

    with qtbot.waitSignal(nas_manager.connectionStatusChanged):
        nas_manager.requestConnect(conn_id)

    assert nas_manager.isConnectionMounted(conn_id) is True


def test_mount_for_recording_nfs_does_not_prompt_for_password(nas_manager, qtbot, monkeypatch):
    nas_manager.saveConnection({
        "name": "NFS NAS",
        "protocol": "nfs",
        "host": "nas",
        "share": "export",
    })
    conn_id = nas_manager.connections[0]["id"]

    def fake_mount(conn, mount_point, password, drive_letter):
        mount_point.mkdir(parents=True, exist_ok=True)
        return True, None, None

    monkeypatch.setattr("backend.nas_manager.mount_share", fake_mount)

    with qtbot.waitSignal(nas_manager.recordingPathReady) as blocker:
        nas_manager.mountForRecording(conn_id, "cam-1")

    assert blocker.args[0] == "cam-1"
