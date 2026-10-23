"""Точка входа NexoraLauncher (GUI на PySide6).

По умолчанию backend запускается внутри процесса на случайном порту.
Для подключения к отдельно запущенному backend::

    python main.py --backend-url http://127.0.0.1:8000/api/v1 --token <токен>
"""

import argparse
import os
import sys
from pathlib import Path

_project_root = Path(__file__).resolve().parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from frontend.utils.logger import logger, setup_logging  # noqa: E402
from shared.paths import ensure_directories  # noqa: E402
from shared.version import APP_NAME, APP_VERSION  # noqa: E402


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="nexoralauncher", description=f"{APP_NAME} {APP_VERSION}")
    parser.add_argument("--backend-url", help="URL внешнего backend (…/api/v1)")
    parser.add_argument("--token", default="", help="Токен доступа внешнего backend")
    parser.add_argument("--debug", action="store_true", help="Подробные логи")
    parser.add_argument("--ui", choices=("classic", "quick"), default=os.environ.get("NEXORA_UI", "quick"),
                        help="Интерфейс: quick (основной, на QML) или classic (прежний, на виджетах)")
    parser.add_argument("--self-test", action="store_true",
                        help="Проверить запуск backend и загрузку модулей GUI без открытия окна")
    parser.add_argument("--version", action="version", version=f"{APP_NAME} {APP_VERSION}")
    return parser.parse_args(argv)


def _check_quick_ui(api) -> None:
    """Интерфейс QML загружается без ошибок (в сборке есть все модули Qt Quick)."""
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from frontend.quick.app import QuickUi
    app = QApplication.instance() or QApplication(sys.argv[:1])
    ui = QuickUi(api)
    errors: list[str] = []
    ui.engine.warnings.connect(lambda items: errors.extend(w.toString() for w in items))
    loaded = ui.show()
    app.processEvents()
    ui.close()
    if not loaded or errors:
        raise RuntimeError("QML: " + "; ".join(errors or ["окно не загрузилось"]))


def self_test() -> int:
    """Проверка сборки: backend отвечает, модули GUI импортируются. Код возврата 0 — успех."""
    from frontend.backend_runner import EmbeddedBackend
    from frontend.services.api_client import ApiClient

    backend = EmbeddedBackend()
    try:
        backend.start()
        api = ApiClient(backend.base_url, backend.token)
        assert api.health()["status"] == "healthy"
        api.settings()
        api.instances()
        api.close()
        import frontend.app  # noqa: F401 — проверка, что все страницы собраны
        from frontend.app import _page_factories
        _page_factories()
        _check_quick_ui(api)
    except Exception:  # noqa: BLE001
        logger.exception("Self-test не пройден")
        return 1
    finally:
        backend.stop()
    logger.info("Self-test пройден")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    ensure_directories()
    setup_logging(args.debug)
    logger.info(f"{APP_NAME} {APP_VERSION} запускается")
    if args.self_test:
        return self_test()

    from PySide6.QtWidgets import QApplication, QMessageBox

    from frontend.services.api_client import ApiClient
    from shared.config import AppConfig
    from shared.i18n import set_language

    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(APP_VERSION)
    app.setOrganizationName("Atomfren")

    config = AppConfig.load()
    set_language(config.language)
    # Стандартные кнопки Qt (Да/Нет, Сохранить/Отмена) на языке интерфейса
    from PySide6.QtCore import QLibraryInfo, QTranslator
    qt_translator = QTranslator(app)
    if qt_translator.load(f"qtbase_{config.language}",
                          QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)):
        app.installTranslator(qt_translator)

    from frontend.theme import apply_theme
    apply_theme(app, config.appearance_mode)

    backend = None
    if args.backend_url:
        api = ApiClient(args.backend_url, args.token)
    else:
        from frontend.backend_runner import EmbeddedBackend
        backend = EmbeddedBackend()
        try:
            backend.start()
        except Exception as e:  # noqa: BLE001 — показываем пользователю и выходим
            logger.exception("Не удалось запустить backend")
            QMessageBox.critical(None, APP_NAME, f"Не удалось запустить backend:\n{e}")
            return 1
        api = ApiClient(backend.base_url, backend.token)

    try:
        api.health()
    except Exception as e:  # noqa: BLE001
        QMessageBox.critical(None, APP_NAME, f"Backend недоступен:\n{e}")
        return 1

    if args.ui == "quick":
        from frontend.quick.app import QuickUi
        ui = QuickUi(api, dark=config.appearance_mode != "light", last_instance=config.last_instance)
        if not ui.show():
            QMessageBox.critical(None, APP_NAME, "Не удалось загрузить интерфейс QML (см. логи)")
            return 1
    else:
        from frontend.app import MainWindow
        window = MainWindow(api)
        window.show()
    code = app.exec()

    if args.ui == "quick":
        ui.close()
    api.close()
    if backend:
        backend.stop()
    logger.info("Лаунчер закрыт")
    return code


if __name__ == "__main__":
    sys.exit(main())
