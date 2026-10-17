from PySide6.QtCore import QObject, Slot

class QmlBridge(QObject):

    def __init__(self):
        super().__init__()

    @Slot(str, result=str)
    def helloWorld(self, input: str) -> str:
        print(input)
        return f"Hello: {input}"
