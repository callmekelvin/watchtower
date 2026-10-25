import sys
import os
import platform

from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlApplicationEngine

from backend.qml_bridge import QmlBridge
from backend.device_manager import DeviceManager
from backend.capture_session_manager import CaptureSessionManager
from backend.storage_manager import StorageManager


def app_dir():
    # PyInstaller onefile extracts files to sys._MEIPASS
    if hasattr(sys, '_MEIPASS'):
        return sys._MEIPASS
    # Normal Python run
    return os.path.dirname(os.path.abspath(__file__))

def main():
    # For Linux, don't autoset encoding
    # Qt Multimedia's FFmpeg backend on Linux auto-selects VAAPI for H.264 encoding
    if platform.system() == "Linux":
        os.environ.setdefault("QT_FFMPEG_ENCODING_HW_DEVICE_TYPES", "")

    # Create QT UI Application
    app = QGuiApplication(sys.argv)
    engine = QQmlApplicationEngine()
    engine.addImportPath(app_dir())

    # Backend layer that observes hardware camera changes on a worker thread
    device_manager = DeviceManager()

    # Manages storage policy, disk usage, and the background purge worker.
    storage_manager = StorageManager()

    # Manages live camera capture sessions on dedicated threads
    capture_manager = CaptureSessionManager(device_manager, storage_manager)

    # Adapter layer that exposes backend state to QML
    bridge = QmlBridge(device_manager, capture_manager, storage_manager)

    # A fatal recording error should terminate the application rather than
    # repeatedly attempting to restart recording.
    def _on_fatal_error(message: str) -> None:
        print(f"FATAL: {message}", file=sys.stderr)
        app.exit(1)

    bridge.fatalErrorOccurred.connect(_on_fatal_error)

    # Ensure background threads shut down cleanly before the app exits
    app.aboutToQuit.connect(capture_manager.shutdown)
    app.aboutToQuit.connect(device_manager.shutdown)
    app.aboutToQuit.connect(storage_manager.shutdown)

    # Connect Bridge (QT Backend) to QML UI
    engine.rootContext().setContextProperty("bridge", bridge)

    engine.loadFromModule("ui", "home")
    if not engine.rootObjects():
        print("Failed to load QML module 'ui'")
        sys.exit(-1)

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
