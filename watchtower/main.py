import sys

from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlApplicationEngine

from backend.qml_bridge import QmlBridge

def main():
    # Create Qt UI Application
    app = QGuiApplication(sys.argv)
    engine = QQmlApplicationEngine()
    engine.addImportPath(sys.path[0])
    print(sys.path[0])

    # Connect Bridge (QT Backend) to QML UI
    bridge = QmlBridge()
    engine.rootContext().setContextProperty("bridge", bridge)

    engine.loadFromModule("ui", "home")
    if not engine.rootObjects():
        sys.exit(-1)

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
