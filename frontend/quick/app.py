"""Запуск интерфейса на QML: движок, глобальные объекты, провайдер картинок."""

import os
from pathlib import Path

from PySide6.QtCore import QUrl
from PySide6.QtGui import QFont, QGuiApplication, QIcon
from PySide6.QtQml import QQmlApplicationEngine

from frontend.quick.bridge import I18nBridge, Shell, load_fonts
from frontend.quick.build import BuildDetails
from frontend.quick.catalog import Catalog
from frontend.quick.doctor import CrashReport
from frontend.quick.images import NxImageProvider
from frontend.quick.library import Library
from frontend.quick.logs import LogView
from frontend.quick.network import Network
from frontend.quick.optifine import OptiFine
from frontend.quick.settings import Settings
from frontend.quick.wizard import Wizard
from frontend.services.api_client import ApiClient
from frontend.utils.logger import logger
from frontend.utils.worker import run_async

QML_DIR = Path(__file__).resolve().parent / "qml"


class QuickUi:
    """Держит движок и объекты моста, пока открыто окно."""

    def __init__(self, api: ApiClient, dark: bool = True, last_instance: str = ""):
        os.environ.setdefault("QT_QUICK_CONTROLS_STYLE", "Basic")
        fonts = load_fonts()
        font = QFont(fonts[0])
        font.setPixelSize(13)
        QGuiApplication.setFont(font)
        icon = QML_DIR.parents[2] / "resources" / "icon.png"
        if icon.exists():
            QGuiApplication.setWindowIcon(QIcon(str(icon)))

        self.api = api
        self.i18n = I18nBridge()
        self.shell = Shell(api, dark, fonts)
        self.library = Library(api, self.shell, last_instance)
        self.build = BuildDetails(api, self.shell, self.library)
        self.logs = LogView(api, self.library)
        self.crash = CrashReport(api, self.shell, self.library)
        self.catalog = Catalog(api, self.shell, self.library)
        self.wizard = Wizard(api, self.shell, self.library)
        self.network = Network(api, self.shell, self.library)
        self.settings = Settings(api, self.shell)
        self.optifine = OptiFine(api, self.shell, self.library)

        self.engine = QQmlApplicationEngine()
        self.engine.addImageProvider("nx", NxImageProvider(api.download_bytes))
        self.engine.addImportPath(str(QML_DIR))
        ctx = self.engine.rootContext()
        for name, obj in (("I18n", self.i18n), ("Shell", self.shell), ("Library", self.library),
                          ("Build", self.build), ("Logs", self.logs), ("Catalog", self.catalog),
                          ("Wizard", self.wizard), ("Network", self.network), ("Prefs", self.settings),
                          ("OptiFine", self.optifine), ("Crash", self.crash)):
            ctx.setContextProperty(name, obj)
        self._root = None  # корневой объект QML: заполняется в show()
        self._minimized_for: str = ""
        self.library.gameStarted.connect(self._on_game_started)
        self.library.gameExited.connect(self._on_game_exited)
        self.engine.warnings.connect(lambda warnings: [logger.warning(f"QML: {w.toString()}") for w in warnings])

    def _on_game_started(self, name: str) -> None:
        """Сворачивает окно, если включено «Сворачивать лаунчер при запуске игры»."""
        def done(settings: dict) -> None:
            window = self.window
            if settings.get("hide_on_launch") and window is not None:
                self._minimized_for = name
                window.showMinimized()

        run_async(self.api.settings, done, lambda msg: logger.warning(f"Настройки не загружены: {msg}"),
                  owner=self.library)

    def _on_game_exited(self, name: str, _code: int) -> None:
        """Игра закрыта — возвращаем окно, если сворачивали его сами."""
        window = self.window
        if self._minimized_for == name and window is not None:
            self._minimized_for = ""
            window.showNormal()
            window.raise_()
            window.requestActivate()

    def show(self) -> bool:
        from PySide6.QtQml import qmlRegisterType

        from frontend.quick.skinview import SkinView
        qmlRegisterType(SkinView, "Nexora.Skin", 1, 0, "NxSkinView")
        self.engine.load(QUrl.fromLocalFile(str(QML_DIR / "Main.qml")))
        roots = self.engine.rootObjects()
        # Ссылку на окно держим здесь: у корневого объекта нет родителя, и PySide отдаёт его
        # Python — временная обёртка, собранная сборщиком мусора, удалила бы окно вместе с детьми
        self._root = roots[0] if roots else None
        if self._root is not None:
            # Проверка обновлений начинается после открытия окна и повторяется при появлении сети
            self.settings.start_auto_check()
        return self._root is not None

    @property
    def window(self):
        return self._root

    def close(self) -> None:
        """Сначала удаляем движок: иначе QML переживёт объекты моста и засорит лог ошибками."""
        self.library.stop_polling()
        self.network.deactivate()
        self.shell.tracker.blockSignals(True)
        self._root = None
        engine, self.engine = self.engine, None
        if engine is not None:
            engine.deleteLater()
            del engine
            from PySide6.QtCore import QCoreApplication, QEvent
            QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete.value)
