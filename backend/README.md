# NexoraLauncher Backend

REST API лаунчера на FastAPI. Обычно запускается внутри GUI-процесса (`frontend/backend_runner.py`), но может работать и отдельно.

## Запуск отдельно

```bash
pip install -r requirements.txt
set NEXORA_BACKEND_API_TOKEN=secret     # Linux/macOS: export NEXORA_BACKEND_API_TOKEN=secret
python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
```

Все запросы, кроме `/api/v1/health`, должны содержать заголовок `X-Nexora-Token`.
Если токен не задан, проверка отключена и доступна документация `http://127.0.0.1:8000/docs`.

Переменные окружения (префикс `NEXORA_BACKEND_`): `API_TOKEN`, `DEBUG`, `LOG_LEVEL`, `AI_MODEL_PATH`, `AI_N_CTX`, `AI_N_THREADS`.
`NEXORA_HOME` задаёт портативную папку данных.

## Устройство

```
api/v1/      тонкие эндпоинты: валидация (pydantic) → вызов core
core/        бизнес-логика
  instance.py        инстансы (instance.json + .minecraft)
  minecraft.py       установка версий и загрузчиков, команда запуска
  launcher.py        сценарий запуска: установка → авторизация → процесс
  process_manager.py процессы игры, логи, статистика
  content.py         моды/ресурспаки/шейдеры из Modrinth, миры
  pack_manager.py    экспорт/импорт .zip и .mrpack
  auth.py            офлайн- и Microsoft-аккаунты (токены зашифрованы)
  tasks.py           фоновые задачи с прогрессом
  errors.py          исключения → HTTP-коды (обработчик в main.py)
services/    Modrinth (httpx, кэш, проверка хэшей), локальный AI
```

Ошибки бизнес-логики (`NotFoundError`, `ConflictError`, `BadRequestError`, …) переводятся в ответы `{"detail": "..."}` с нужным кодом.

## Основные эндпоинты (`/api/v1`)

| Метод | Путь | Назначение |
|---|---|---|
| GET | `/health` | Проверка (без токена) |
| GET | `/tasks/`, `/tasks/{id}` | Фоновые задачи; `POST /tasks/{id}/cancel` |
| GET/POST | `/instances/` | Список / создание инстанса |
| GET/PATCH/DELETE | `/instances/{name}` | Инстанс |
| POST | `/instances/{name}/launch` | Запуск (задача) |
| POST | `/instances/{name}/prepare` | Установка/проверка файлов (задача) |
| POST | `/instances/{name}/rename`, `/duplicate`, `/export` | Операции с инстансом |
| POST | `/instances/import` | Импорт `.zip` / `.mrpack` / папки Prism, MultiMC, CurseForge (задача) |
| GET | `/instances/import/foreign` | Сборки других лаунчеров, найденные на компьютере |
| GET | `/instances/{name}/log` | Последний лог запуска из файла |
| GET/POST | `/instances/{name}/content/{type}` | Установленный контент / установка из Modrinth (задача) |
| PATCH/DELETE | `/instances/{name}/content/{type}/{file}` | Вкл./выкл. / удалить |
| GET/POST/DELETE | `/instances/{name}/worlds…` | Миры: список, импорт, экспорт, удаление |
| GET | `/content/search` | Поиск Modrinth (`project_type`: mod, modpack, resourcepack, shader, plugin; `side`: client/server) |
| POST | `/modpacks/install` | Установка модпака как инстанса (задача) |
| GET | `/minecraft/versions/available`, `/installed` | Версии игры |
| GET | `/minecraft/loaders/{loader}/versions` | Версии загрузчика для версии игры |
| GET/DELETE | `/minecraft/processes/{pid}` | Процесс игры / остановка; `…/log` — вывод |
| GET/POST/DELETE | `/auth/accounts…` | Аккаунты; `POST /auth/offline/login`, `POST /auth/microsoft/login/start` |
| GET/PATCH | `/settings/` | Настройки; `GET /settings/java/` — найденные Java |
| GET/POST/PATCH/DELETE | `/servers/…` | Серверы; `…/ping`, `…/connect` |
| GET/POST | `/ai/status`, `/ai/chat` | Локальный AI (потоковый NDJSON) |
| GET/POST | `/hosting/servers` | Свои серверы; создание (`core`: fabric/vanilla/paper/purpur, нужен `accept_eula`) |
| GET/PATCH/DELETE | `/hosting/servers/{name}` | Сервер: статус, публичный адрес, игроки / настройки / удаление |
| POST | `/hosting/servers/{name}/start`, `/stop`, `/command`, `/install` | Управление сервером |
| GET/PATCH | `/hosting/servers/{name}/properties`, GET `…/console` | server.properties, консоль |
| GET/POST/DELETE | `/hosting/servers/{name}/mods…` | Моды (Fabric) или плагины (Paper/Purpur) |
| GET/POST/DELETE | `/hosting/servers/{name}/backups…` | Резервные копии мира; `…/{file}/restore` |
| POST | `/instances/{name}/friends/prepare` | «Играть с друзьями»: установка туннеля e4mc |
| GET/POST | `/app/update`, `/app/update/download`, `/app/update/apply` | Автообновление лаунчера |
| GET | `/optifine/versions`, `/optifine/downloaded` | Версии OptiFine с optifine.net, скачанные файлы |
| GET/POST/DELETE | `/instances/{name}/optifine` | OptiFine инстанса: статус / установка из файла / удаление |
| GET | `/instances/{name}/logs`, `…/logs/analyze?source=` | Умные логи: список логов и разбор |
| POST | `/instances/{name}/logs/share` | Публикация лога на mclo.gs |
