from pathlib import Path
from unittest.mock import MagicMock

import pytest

from backend.nas_connection import NasConnection
from backend.nas_mount_helper import (
    build_mount_command,
    build_unmount_command,
    get_app_data_dir,
    get_default_mount_point,
    is_likely_nas_mount,
    sanitize_host,
    sanitize_mount_point,
    sanitize_share,
)


def test_sanitize_host_accepts_simple_hostname():
    assert sanitize_host("nas.local") == "nas.local"


def test_sanitize_host_rejects_empty():
    with pytest.raises(ValueError):
        sanitize_host("  ")


def test_sanitize_host_rejects_shell_metacharacters():
    with pytest.raises(ValueError):
        sanitize_host("nas;rm -rf")


def test_sanitize_share_normalizes_backslashes():
    assert sanitize_share("\\share\\folder") == "share/folder"


def test_sanitize_share_rejects_path_traversal():
    with pytest.raises(ValueError):
        sanitize_share("share/../etc")


def test_sanitize_share_rejects_shell_metacharacters():
    with pytest.raises(ValueError):
        sanitize_share("share; rm -rf")


def test_sanitize_mount_point_defaults_to_app_data(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "backend.nas_mount_helper.get_app_data_dir", lambda: tmp_path / "Watchtower"
    )
    point = sanitize_mount_point(None, "conn-1")
    assert point == tmp_path / "Watchtower" / "mounts" / "conn-1"


def test_sanitize_mount_point_rejects_outside_app_data(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "backend.nas_mount_helper.get_app_data_dir", lambda: tmp_path / "Watchtower"
    )
    with pytest.raises(ValueError):
        sanitize_mount_point("/tmp/mounts/conn-1", "conn-1")


def test_default_mount_point_under_app_data(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "backend.nas_mount_helper.get_app_data_dir", lambda: tmp_path / "Watchtower"
    )
    assert get_default_mount_point("abc") == tmp_path / "Watchtower" / "mounts" / "abc"


def test_build_linux_smb_mount_command(monkeypatch, tmp_path):
    monkeypatch.setattr("backend.nas_mount_helper.platform.system", lambda: "Linux")
    conn = NasConnection(
        name="Test", protocol="smb", host="nas", share="recordings", username="user"
    )
    mount_point = tmp_path / "mount"
    cmd, extras = build_mount_command(conn, mount_point, password="secret")

    assert cmd[0] == "sudo"
    assert cmd[1] == "mount"
    assert cmd[2] == "-t"
    assert cmd[3] == "cifs"
    assert cmd[4] == "//nas/recordings"
    assert cmd[5] == str(mount_point)
    assert "-o" in cmd
    opts = cmd[cmd.index("-o") + 1]
    assert "rw" in opts
    assert "username=user" in opts
    assert extras["env"]["PASSWD"] == "secret"


def test_build_linux_nfs_mount_command(monkeypatch, tmp_path):
    monkeypatch.setattr("backend.nas_mount_helper.platform.system", lambda: "Linux")
    conn = NasConnection(
        name="Test", protocol="nfs", host="nas", share="export", mount_options="soft"
    )
    mount_point = tmp_path / "mount"
    cmd, extras = build_mount_command(conn, mount_point)

    assert cmd[0] == "sudo"
    assert cmd[1] == "mount"
    assert cmd[2] == "-t"
    assert cmd[3] == "nfs"
    assert cmd[4] == "nas:/export"
    assert cmd[5] == str(mount_point)
    assert "rw,soft" in cmd
    assert "env" not in extras


def test_build_macos_smb_mount_command(monkeypatch, tmp_path):
    monkeypatch.setattr("backend.nas_mount_helper.platform.system", lambda: "Darwin")
    conn = NasConnection(
        name="Test", protocol="smb", host="nas", share="recordings", username="user"
    )
    mount_point = tmp_path / "mount"
    cmd, extras = build_mount_command(conn, mount_point, password="secret")

    assert cmd[0] == "mount_smbfs"
    assert cmd[-1] == str(mount_point)
    assert "//user:secret@nas/recordings" in cmd


def test_build_macos_nfs_mount_command(monkeypatch, tmp_path):
    monkeypatch.setattr("backend.nas_mount_helper.platform.system", lambda: "Darwin")
    conn = NasConnection(
        name="Test", protocol="nfs", host="nas", share="export", mount_options="resvport"
    )
    mount_point = tmp_path / "mount"
    cmd, extras = build_mount_command(conn, mount_point)

    assert cmd[0] == "sudo"
    assert cmd[1] == "mount"
    assert cmd[2] == "-t"
    assert cmd[3] == "nfs"
    assert cmd[4] == "nas:/export"


def test_build_unmount_command_linux(monkeypatch, tmp_path):
    monkeypatch.setattr("backend.nas_mount_helper.platform.system", lambda: "Linux")
    cmd, drive = build_unmount_command(tmp_path / "mount")
    assert cmd == ["sudo", "umount", str(tmp_path / "mount")]
    assert drive is None


def test_build_unmount_command_windows(monkeypatch, tmp_path):
    monkeypatch.setattr("backend.nas_mount_helper.platform.system", lambda: "Windows")
    cmd, drive = build_unmount_command(tmp_path / "mount", drive_letter="Z")
    assert cmd == ["net", "use", "Z:", "/delete"]
    assert drive == "Z"


def test_is_likely_nas_mount(monkeypatch, tmp_path):
    app_dir = tmp_path / "Watchtower"
    monkeypatch.setattr("backend.nas_mount_helper.get_app_data_dir", lambda: app_dir)
    mount_point = app_dir / "mounts" / "conn-1"
    mount_point.mkdir(parents=True)
    assert is_likely_nas_mount(str(mount_point)) is True
    assert is_likely_nas_mount(str(tmp_path / "other")) is False


def test_sanitize_host_preserves_ipv4_like_string():
    assert sanitize_host("192.168.1.10") == "192.168.1.10"
