import os
import platform
import re
import shutil
import signal
import socket
import string
import subprocess
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from backend.nas_connection import NasConnection, NasProtocol


# ---------------------------------------------------------------------------
# Application data / mount point paths
# ---------------------------------------------------------------------------

def get_app_data_dir() -> Path:
    """Return the OS-specific application data directory for Watchtower."""
    system = platform.system()
    if system == "Windows":
        base = os.environ.get("LOCALAPPDATA")
        if base:
            return Path(base) / "Watchtower"
        return Path.home() / "AppData" / "Local" / "Watchtower"
    if system == "Darwin":
        return Path.home() / "Library" / "Application Support" / "Watchtower"
    # Linux and other POSIX
    return Path.home() / ".local" / "share" / "Watchtower"


def get_default_mount_point(connection_id: str) -> Path:
    """Return the default mount point for a connection."""
    return get_app_data_dir() / "mounts" / connection_id


# ---------------------------------------------------------------------------
# Input sanitization
# ---------------------------------------------------------------------------

def sanitize_host(host: str) -> str:
    """Validate and return a shell-safe host string."""
    host = host.strip()
    if not host:
        raise ValueError("Host cannot be empty")
    if not re.match(r"^[A-Za-z0-9][A-Za-z0-9._\-]*$", host):
        raise ValueError(f"Invalid host: {host}")
    return host


def sanitize_share(share: str) -> str:
    """Validate and return a shell-safe share / export path."""
    share = share.strip().lstrip("\\/").replace("\\", "/")
    if not share:
        raise ValueError("Share cannot be empty")
    parts = share.split("/")
    if ".." in parts:
        raise ValueError(f"Invalid share path: {share}")
    if re.search(r"[;&|`$\n\r]", share):
        raise ValueError(f"Invalid share path: {share}")
    return share


def sanitize_mount_point(path: Optional[str], connection_id: str) -> Path:
    """Validate that a mount point lives under the app data directory."""
    if not path:
        mount_point = get_default_mount_point(connection_id)
    else:
        mount_point = Path(path).expanduser().resolve()

    expected_root = (get_app_data_dir() / "mounts").resolve()
    try:
        mount_point.relative_to(expected_root)
    except ValueError as exc:
        raise ValueError(
            f"Mount point must be under {expected_root}: {mount_point}"
        ) from exc
    return mount_point


def ensure_mount_point_dir(mount_point: Path) -> None:
    """Create the mount point directory if it does not exist."""
    mount_point.mkdir(parents=True, exist_ok=True)


# Default NFS mount options used to make the mount fail fast instead of
# hanging the recorder thread when the network drops.
_DEFAULT_NFS_OPTIONS = ["soft", "timeo=50", "retrans=3"]

# Privileged helper scripts used on Linux instead of calling mount/umount
# directly.  These are installed by scripts/install-mount-helper.sh and are
# validated by a narrow sudoers rule, so the user is never prompted for a
# password at runtime.
_LINUX_MOUNT_HELPER = "watchtower-mount"
_LINUX_UNMOUNT_HELPER = "watchtower-umount"


def _build_nfs_options(connection: NasConnection) -> str:
    """Build an NFS options string with resilience defaults appended.

    User-supplied options are preserved and defaults are only added when
    they (or a conflicting option) are not already present.
    """
    parts: List[str] = []
    if connection.mount_options:
        parts = [opt.strip() for opt in connection.mount_options.split(",") if opt.strip()]

    # Ensure a read/write option is present unless the user specified ro/rw.
    if not any(p.lower() in ("rw", "ro") for p in parts):
        parts.insert(0, "rw")

    existing_keys = {p.split("=", 1)[0].lower(): p for p in parts}

    for default in _DEFAULT_NFS_OPTIONS:
        key = default.split("=", 1)[0].lower()
        # Do not override an explicit soft/hard choice.
        if key == "soft" and ("soft" in existing_keys or "hard" in existing_keys):
            continue
        if key in existing_keys:
            continue
        parts.append(default)

    return ",".join(parts)


def is_mount_healthy(mount_point: Path) -> bool:
    """Return True if the mount point exists and is writable.

    For NAS mount points the writability check is performed in a subprocess
    so a stale network mount cannot hang the caller.
    """
    try:
        if not mount_point.exists():
            return False
    except OSError:
        return False

    path_str = str(mount_point)
    if is_likely_nas_mount(path_str):
        return is_nas_path_reachable(path_str)

    return os.access(path_str, os.W_OK)


# ---------------------------------------------------------------------------
# Mount / unmount command builders
# ---------------------------------------------------------------------------

def find_available_drive_letter() -> Optional[str]:
    """Return an unused Windows drive letter, or None if none is available."""
    if platform.system() != "Windows":
        return None
    used = set()
    for letter in string.ascii_uppercase[2:26]:  # D: through Z:
        if os.path.exists(f"{letter}:"):
            used.add(letter)
    for letter in reversed(string.ascii_uppercase[2:26]):
        if letter not in used:
            return letter
    return None


def build_mount_command(
    connection: NasConnection,
    mount_point: Path,
    password: Optional[str] = None,
    drive_letter: Optional[str] = None,
) -> Tuple[List[str], Dict[str, str]]:
    """Build a mount command and extra kwargs for subprocess.run.

    Returns
    -------
    cmd:
        Argument list suitable for ``subprocess.run(..., shell=False)``.
    extras:
        Dictionary that may contain ``env`` and/or ``input`` to pass to
        ``subprocess.run``.  ``env`` is merged with ``os.environ`` by the
        caller; ``input`` is bytes to feed to the command's stdin.
    """
    system = platform.system()
    if system == "Windows":
        return _build_windows_mount(connection, mount_point, password, drive_letter)
    if system == "Darwin":
        return _build_macos_mount(connection, mount_point, password)
    return _build_linux_mount(connection, mount_point, password)


def _build_linux_mount(
    connection: NasConnection,
    mount_point: Path,
    password: Optional[str],
) -> Tuple[List[str], Dict[str, str]]:
    host = sanitize_host(connection.host)
    share = sanitize_share(connection.share)

    if connection.protocol == NasProtocol.SMB:
        source = f"//{host}/{share}"
        # The mount point must be the last positional argument so the helper
        # script can validate it.
        cmd: List[str] = [
            "sudo",
            _LINUX_MOUNT_HELPER,
            "-t",
            "cifs",
        ]
        options: List[str] = ["rw"]
        if connection.username:
            options.append(f"username={connection.username}")
        if connection.domain:
            options.append(f"domain={connection.domain}")
        if connection.mount_options:
            options.extend(connection.mount_options.split(","))
        cmd.extend(["-o", ",".join(options)])
        cmd.extend([source, str(mount_point)])

        extras: Dict[str, str] = {}
        if password:
            # mount.cifs reads the password from the PASSWD environment
            # variable, keeping it out of the process list.
            extras["env"] = {"PASSWD": password}
        return cmd, extras

    if connection.protocol == NasProtocol.NFS:
        source = f"{host}:/{share}"
        options = _build_nfs_options(connection)
        cmd = [
            "sudo",
            _LINUX_MOUNT_HELPER,
            "-t",
            "nfs",
            "-o",
            options,
            source,
            str(mount_point),
        ]
        return cmd, {}

    raise ValueError(f"Unsupported protocol: {connection.protocol}")


def _build_macos_mount(
    connection: NasConnection,
    mount_point: Path,
    password: Optional[str],
) -> Tuple[List[str], Dict[str, str]]:
    host = sanitize_host(connection.host)
    share = sanitize_share(connection.share)

    if connection.protocol == NasProtocol.SMB:
        # mount_smbfs does not support an environment-variable password, so we
        # embed credentials in the mount URL for the duration of the command.
        # The password is never written to disk.
        user_part = ""
        if connection.username:
            creds = connection.username
            if password:
                creds = f"{creds}:{password}"
            user_part = f"{creds}@"
        url = f"//{user_part}{host}/{share}"
        cmd = ["mount_smbfs"]
        if connection.mount_options:
            cmd.extend(["-o", connection.mount_options])
        cmd.extend([url, str(mount_point)])
        return cmd, {}

    if connection.protocol == NasProtocol.NFS:
        source = f"{host}:/{share}"
        options = _build_nfs_options(connection)
        cmd = ["sudo", "mount", "-t", "nfs", source, str(mount_point), "-o", options]
        return cmd, {}

    raise ValueError(f"Unsupported protocol: {connection.protocol}")


def _build_windows_mount(
    connection: NasConnection,
    mount_point: Path,
    password: Optional[str],
    drive_letter: Optional[str],
) -> Tuple[List[str], Dict[str, str]]:
    host = sanitize_host(connection.host)
    share = sanitize_share(connection.share)

    if drive_letter is None:
        drive_letter = find_available_drive_letter()
    if drive_letter is None:
        raise RuntimeError("No available Windows drive letter for NAS mount")

    if connection.protocol == NasProtocol.SMB:
        user = connection.username or ""
        if connection.domain:
            user = f"{connection.domain}\\{user}"
        remote = f"\\\\{host}\\{share}"
        cmd = [
            "net",
            "use",
            f"{drive_letter}:",
            remote,
            "*",
            f"/user:{user}",
            "/persistent:no",
        ]
        extras: Dict[str, str] = {}
        if password:
            extras["input"] = password
        return cmd, extras, drive_letter

    if connection.protocol == NasProtocol.NFS:
        # Windows NFS client syntax (requires the Optional Features NFS client).
        options = _build_nfs_options(connection)
        cmd = [
            "mount",
            f"{host}:/{share}",
            f"{drive_letter}:",
        ]
        cmd[1:1] = ["-o:" + options]
        return cmd, {}, drive_letter

    raise ValueError(f"Unsupported protocol: {connection.protocol}")


def build_unmount_command(
    mount_point: Path,
    drive_letter: Optional[str] = None,
    lazy: bool = False,
    force: bool = False,
) -> Tuple[List[str], Optional[str]]:
    """Build an unmount command for the current platform.

    Returns the command list and the Windows drive letter that must be
    released, if applicable.
    """
    system = platform.system()
    if system == "Windows":
        if drive_letter is None:
            raise ValueError("Windows unmount requires a drive letter")
        return ["net", "use", f"{drive_letter}:", "/delete"], drive_letter

    flags: List[str] = []
    if lazy:
        flags.append("-l")
    if force:
        flags.append("-f")

    if system == "Darwin":
        return ["sudo", "umount", *flags, str(mount_point)], None
    return ["sudo", _LINUX_UNMOUNT_HELPER, *flags, str(mount_point)], None


def build_junction_command(
    mount_point: Path,
    drive_letter: str,
    create: bool = True,
) -> List[str]:
    """Build a Windows junction create/remove command."""
    if create:
        return ["cmd", "/c", "mklink", "/J", str(mount_point), f"{drive_letter}:\\"]
    return ["cmd", "/c", "rmdir", str(mount_point)]


# ---------------------------------------------------------------------------
# Execution wrappers
# ---------------------------------------------------------------------------

def _run_subprocess(
    cmd: List[str],
    env: Optional[Dict[str, str]] = None,
    input_text: Optional[str] = None,
) -> subprocess.CompletedProcess:
    """Run a subprocess with shell=False and optional env/stdin input."""
    merged_env = None
    if env:
        merged_env = {**os.environ, **env}
    input_bytes = input_text.encode("utf-8") if input_text is not None else None
    return subprocess.run(
        cmd,
        shell=False,
        check=False,
        capture_output=True,
        text=True,
        env=merged_env,
        input=input_bytes,
    )


def mount_share(
    connection: NasConnection,
    mount_point: Path,
    password: Optional[str] = None,
    drive_letter: Optional[str] = None,
) -> Tuple[bool, Optional[str], Optional[str]]:
    """Mount a NAS share to the given mount point.

    Returns
    -------
    success:
        True if the mount succeeded.
    drive_letter:
        The Windows drive letter used, or None on other platforms.
    error_message:
        None on success, otherwise a descriptive error string.
    """
    ensure_mount_point_dir(mount_point)

    system = platform.system()
    if system == "Windows":
        return _mount_windows(connection, mount_point, password, drive_letter)

    cmd, extras = build_mount_command(connection, mount_point, password)
    result = _run_subprocess(
        cmd,
        env=extras.get("env"),
        input_text=extras.get("input"),
    )
    if result.returncode != 0:
        return False, None, f"Mount failed ({result.returncode}): {result.stderr or result.stdout}"
    if not is_mount_healthy(mount_point):
        return False, None, f"Mount succeeded but {mount_point} is not writable"
    return True, None, None


def _mount_windows(
    connection: NasConnection,
    mount_point: Path,
    password: Optional[str],
    drive_letter: Optional[str],
) -> Tuple[bool, Optional[str], Optional[str]]:
    cmd, extras, drive_letter = _build_windows_mount(
        connection, mount_point, password, drive_letter
    )
    result = _run_subprocess(
        cmd,
        input_text=extras.get("input"),
    )
    if result.returncode != 0:
        return False, None, f"Mount failed ({result.returncode}): {result.stderr or result.stdout}"

    # Create a directory junction from the app-local mount point to the drive.
    if mount_point.exists():
        try:
            mount_point.rmdir()
        except OSError as exc:
            return False, drive_letter, f"Failed to prepare junction point: {exc}"
    junction_cmd = build_junction_command(mount_point, drive_letter, create=True)
    junction_result = _run_subprocess(junction_cmd)
    if junction_result.returncode != 0:
        _run_subprocess(["net", "use", f"{drive_letter}:", "/delete"])
        return (
            False,
            None,
            f"Failed to create junction ({junction_result.returncode}): "
            f"{junction_result.stderr or junction_result.stdout}",
        )

    if not is_mount_healthy(mount_point):
        _run_subprocess(["net", "use", f"{drive_letter}:", "/delete"])
        _run_subprocess(build_junction_command(mount_point, drive_letter, create=False))
        return False, None, f"Mount succeeded but {mount_point} is not writable"

    return True, drive_letter, None


def unmount_share(
    mount_point: Path,
    drive_letter: Optional[str] = None,
    lazy: bool = False,
    force: bool = False,
) -> Tuple[bool, Optional[str]]:
    """Unmount a previously mounted share.

    Returns True on success, otherwise an error message string.
    """
    system = platform.system()
    if system == "Windows" and drive_letter:
        # Remove the junction first, then release the drive letter.
        if mount_point.exists():
            _run_subprocess(build_junction_command(mount_point, drive_letter, create=False))
        result = _run_subprocess(["net", "use", f"{drive_letter}:", "/delete"])
        if result.returncode != 0:
            return False, f"Unmount failed ({result.returncode}): {result.stderr or result.stdout}"
        return True, None

    cmd, _ = build_unmount_command(mount_point, drive_letter, lazy=lazy, force=force)
    result = _run_subprocess(cmd)
    if result.returncode != 0:
        return False, f"Unmount failed ({result.returncode}): {result.stderr or result.stdout}"
    return True, None


# ---------------------------------------------------------------------------
# Free-space fallback for network mounts
# ---------------------------------------------------------------------------

def get_network_free_space_gb(path: str) -> Optional[float]:
    """Return free space in GB using a platform command fallback.

    This is useful when QStorageInfo reports unreliable values for a network
    mount.  Returns None if the value cannot be determined.
    """
    system = platform.system()
    if system == "Windows":
        cmd = ["wmic", "logicaldisk", "get", "size,freespace,caption", "/format:csv"]
    else:
        cmd = ["df", "-k", "--output=avail", path]

    try:
        result = subprocess.run(
            cmd,
            shell=False,
            check=False,
            capture_output=True,
            text=True,
        )
    except Exception:
        return None

    if result.returncode != 0:
        return None

    try:
        if system == "Windows":
            # Parse CSV output for the drive letter mapped to this path.
            return _parse_windows_wmic_output(result.stdout, path)
        # Linux / macOS: second line contains available 1K blocks.
        lines = [line.strip() for line in result.stdout.splitlines() if line.strip()]
        if len(lines) < 2:
            return None
        avail_kb = int(lines[-1])
        return avail_kb / (1024.0 * 1024.0)
    except Exception:
        return None


def _parse_windows_wmic_output(output: str, path: str) -> Optional[float]:
    """Parse WMIC output and return free space in GB for the relevant drive."""
    # Find the drive letter for the given path.  Junctions make this tricky,
    # so we attempt to resolve the path to a drive root first.
    try:
        resolved = os.path.splitdrive(os.path.abspath(path))[0]
    except Exception:
        return None
    if not resolved:
        return None
    drive = resolved.upper()
    for line in output.splitlines():
        parts = [p.strip().strip('"') for p in line.split(",")]
        if len(parts) >= 3 and parts[1].upper() == drive:
            try:
                free_bytes = int(parts[2])
                return free_bytes / (1024.0 ** 3)
            except ValueError:
                continue
    return None


def check_host_port(host: str, port: int, timeout: float = 2.0) -> bool:
    """Return True if a TCP connection to ``host:port`` can be established."""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _run_probe_subprocess(script: str, path: str, timeout: float) -> bool:
    """Run a short Python probe in a subprocess and return True on success."""
    try:
        result = subprocess.run(
            [sys.executable, "-c", script, path],
            capture_output=True,
            text=True,
            timeout=timeout,
            start_new_session=True,
        )
        return result.returncode == 0
    except subprocess.TimeoutExpired:
        return False
    except OSError:
        return False


def probe_nas_write(mount_point: Path, timeout: float = 3.0) -> Tuple[bool, Optional[str]]:
    """Write and delete a unique timestamped file to verify writability.

    The probe runs in a separate subprocess so a stale NFS mount cannot
    block the calling thread. Returns (success, error_message).
    """
    script = (
        "import os, sys, time\n"
        "path = sys.argv[1]\n"
        "probe = os.path.join(path, '.watchtower_probe_' + str(int(time.time() * 1000)))\n"
        "with open(probe, 'w') as f:\n"
        "    f.write('ok')\n"
        "os.remove(probe)\n"
    )
    if _run_probe_subprocess(script, str(mount_point), timeout):
        return True, None
    return False, f"Write probe timed out or failed for {mount_point}"


def is_nas_path_reachable(path: str, timeout: float = 3.0) -> bool:
    """Return True if ``path`` is a writable directory.

    This is executed in a subprocess so a stale network mount cannot hang
    the caller.
    """
    script = (
        "import os, sys\n"
        "path = sys.argv[1]\n"
        "sys.exit(0 if os.path.isdir(path) and os.access(path, os.W_OK) else 1)\n"
    )
    return _run_probe_subprocess(script, path, timeout)


def is_likely_nas_mount(path: str) -> bool:
    """Return True if the path looks like a NAS mount point."""
    try:
        resolved = Path(path).resolve()
    except OSError:
        return False
    app_mounts = (get_app_data_dir() / "mounts").resolve()
    try:
        resolved.relative_to(app_mounts)
        return True
    except ValueError:
        return False
