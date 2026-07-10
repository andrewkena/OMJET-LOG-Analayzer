import faulthandler
import sys
import traceback
from pathlib import Path

from PySide6.QtGui import QIcon
from PySide6.QtWebEngineCore import QWebEngineProfile
from PySide6.QtWidgets import QApplication

from app.core import i18n
from app.core.paths import get_user_data_dir
from app.core.tile_scheme_handler import SCHEME, TileCacheSchemeHandler, register_tile_scheme
from app.ui.main_window import MainWindow

_LOG = get_user_data_dir() / "crash.log"


def _excepthook(exc_type, exc_value, exc_tb):
    text = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
    try:
        _LOG.write_text(text, encoding="utf-8")
    except Exception:
        pass
    sys.__excepthook__(exc_type, exc_value, exc_tb)


def main():
    try:
        faulthandler.enable(file=open(_LOG, "w", encoding="utf-8"), all_threads=True)
    except OSError:
        pass  # non-critical: faulthandler output is a bonus, not required
    sys.excepthook = _excepthook

    i18n.load()
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
