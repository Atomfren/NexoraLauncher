# NexoraLauncher Frontend

GUI на PySide6: основной интерфейс — Qt Quick (`quick/`), прежний на виджетах — `--ui classic`. Все данные приходят из backend по HTTP: импортов `backend.core` во frontend нет.

## Устройство

```
main.py             точка входа: логирование, тема, запуск встроенного backend, окно
backend_runner.py   uvicorn в фоновом потоке: свободный порт + случайный токен
app.py              главное окно: навигация, ленивые страницы, статус задач и игр
services/api_client.py  синхронный httpx-клиент API (ApiError с текстом detail)
utils/worker.py     run_async(): вызов в пуле потоков → колбэк в GUI-потоке
utils/task_tracker.py   опрос /tasks: прогресс и колбэки завершения
widgets.py          Page, Card, кнопки, диалоги, IconCache, форматирование
components.py       карточка инстанса, запуск/остановка
panels.py           установленный контент и миры (используются в диалоге и на страницах)
dialogs/            создание инстанса, диалог инстанса (настройки/контент/миры/логи)
pages/              главная, инстансы, каталог Modrinth, миры, версии, серверы, аккаунты, AI, настройки
theme.py            QSS тёмной и светлой тем

quick/              новый интерфейс на QML
  app.py            QuickUi: движок, объекты моста, провайдер картинок
  bridge.py         Shell (тема, навигация, уведомления, загрузки, аккаунты), I18n
  library.py        Library: модель сборок, кнопка «Играть» (установка, запуск, остановка)
  build.py          BuildDetails: миры, скриншоты, моды, Доктор, «Турбо», точки восстановления
  logs.py catalog.py wizard.py network.py settings.py optifine.py — разделы
  images.py         image://nx/… — иконки Lucide, пиксель-арт, скругление обложек без шейдеров
  art.py icons.py fmt.py — процедурная графика, SVG-иконки, человеческие форматы
  qml/Nexora/       компоненты Nx* (NxTheme — токены дизайна), qml/pages/ — экраны
```

Строки интерфейса: `I18n.t("q.…")` в QML, ключи — в `shared/i18n.py` (тест проверяет и QML).

## Правила

- Блокирующие вызовы API выполняются только через `run_async(...)` или `Page.run(...)`, никогда в GUI-потоке.
- Долгие операции возвращают задачу; на её завершение подписываются через `ctx.tracker.track(task, on_done, on_error)`.
- Все строки интерфейса берутся через `shared.i18n.t("ключ")`. Новые ключи добавляются в оба словаря (ru и en) — полноту проверяет `tests/test_i18n.py`.
- Стили задаются через `objectName` или свойства (`variant="primary"`) в `theme.py`, а не инлайн-стилями.
