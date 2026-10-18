import sys

from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlApplicationEngine

from backend.qml_bridge import QmlBridge
from backend.device_manager import DeviceManager
from backend.capture_session_manager import CaptureSessionManager

def main():
    # Create QT UI Application
    app = QGuiApplication(sys.argv)
    engine = QQmlApplicationEngine()
    engine.addImportPath(sys.path[0])
    print(sys.path[0])

    # Backend layer that observes hardware camera changes on a worker thread
    device_manager = DeviceManager()

    # Manages live camera capture sessions on dedicated threads
    capture_manager = CaptureSessionManager(device_manager)

    # Adapter layer that exposes backend state to QML
    bridge = QmlBridge(device_manager, capture_manager)

    # Ensure background threads shut down cleanly before the app exits
    app.aboutToQuit.connect(capture_manager.shutdown)
    app.aboutToQuit.connect(device_manager.shutdown)

    # Connect Bridge (QT Backend) to QML UI
    engine.rootContext().setContextProperty("bridge", bridge)

    engine.loadFromModule("ui", "home")
    if not engine.rootObjects():
        sys.exit(-1)

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
