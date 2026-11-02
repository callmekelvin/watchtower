#!/bin/bash
# Install the Watchtower mount helpers and a narrow sudoers rule so the
# application can mount/unmount NAS shares without prompting for a password.
set -euo pipefail

if [ "$EUID" -ne 0 ]; then
    echo "This script must be run as root or with sudo" >&2
    exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INSTALL_DIR="/usr/local/bin"

TARGET_USER="${1:-}"
if [ -z "$TARGET_USER" ]; then
    echo "Usage: sudo ./install-mount-helper.sh <username>" >&2
    exit 1
fi

if ! id "$TARGET_USER" &>/dev/null; then
    echo "User does not exist: $TARGET_USER" >&2
    exit 1
fi

install -m 755 -o root -g root "$SCRIPT_DIR/watchtower-mount" "$INSTALL_DIR/watchtower-mount"
install -m 755 -o root -g root "$SCRIPT_DIR/watchtower-umount" "$INSTALL_DIR/watchtower-umount"

SUDOERS_FILE="/etc/sudoers.d/watchtower-mount"
cat > "$SUDOERS_FILE" <<EOF
# Allow $TARGET_USER to mount/unmount Watchtower NAS shares without a password.
$TARGET_USER ALL=(root) NOPASSWD: $INSTALL_DIR/watchtower-mount
$TARGET_USER ALL=(root) NOPASSWD: $INSTALL_DIR/watchtower-umount
EOF
chmod 440 "$SUDOERS_FILE"

if ! visudo -c; then
    echo "Sudoers file validation failed; removing $SUDOERS_FILE" >&2
    rm -f "$SUDOERS_FILE"
    exit 1
fi

echo "Watchtower mount helpers installed for user: $TARGET_USER"
echo "Helpers: $INSTALL_DIR/watchtower-mount, $INSTALL_DIR/watchtower-umount"
echo "Sudoers: $SUDOERS_FILE"
