import pathlib

from PySide6.QtQml import QQmlApplicationEngine


def test_home_qml_loads_without_errors(qtbot):
    engine = QQmlApplicationEngine()
    project_root = pathlib.Path(__file__).parent.parent
    engine.addImportPath(str(project_root))
    engine.loadFromModule("ui", "home")

    assert engine.rootObjects(), f"Failed to load home.qml: {engine.errorString()}"
