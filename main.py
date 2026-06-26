import sys
from pathlib import Path

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from app.ui.main_window import MainWindow


def main():
    app = QApplication(sys.argv)
    app.setWindowIcon(QIcon(str(Path(__file__).resolve().parent / "assets" / "logo.ico")))
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
