import sys

from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlApplicationEngine

from backend.qml_bridge import QmlBridge
from backend.device_manager import DeviceManager

def main():
    # Create QT UI Application
    app = QGuiApplication(sys.argv)
    engine = QQmlApplicationEngine()
    engine.addImportPath(sys.path[0])
    print(sys.path[0])

    # Backend layer that observes hardware camera changes on a worker thread
    device_manager = DeviceManager()

    # Adapter layer that exposes backend state to QML
    bridge = QmlBridge(device_manager)

    # Ensure the worker thread shuts down cleanly before the app exits
    app.aboutToQuit.connect(device_manager.shutdown)

    # Connect Bridge (QT Backend) to QML UI
    engine.rootContext().setContextProperty("bridge", bridge)

    engine.loadFromModule("ui", "home")
    if not engine.rootObjects():
        sys.exit(-1)

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
