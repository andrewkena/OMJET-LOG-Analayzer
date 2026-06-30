import sys
from pathlib import Path

from PySide6.QtGui import QIcon
from PySide6.QtWebEngineCore import QWebEngineProfile
from PySide6.QtWidgets import QApplication

from app.core.tile_scheme_handler import SCHEME, TileCacheSchemeHandler, register_tile_scheme
from app.ui.main_window import MainWindow


def main():
    register_tile_scheme()
    app = QApplication(sys.argv)
    app.setWindowIcon(QIcon(str(Path(__file__).resolve().parent / "assets" / "logo.ico")))
    tile_handler = TileCacheSchemeHandler(app)
    QWebEngineProfile.defaultProfile().installUrlSchemeHandler(SCHEME, tile_handler)
    window = MainWindow(tile_handler=tile_handler)
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
