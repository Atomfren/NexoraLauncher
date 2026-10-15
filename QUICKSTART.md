# Быстрый старт NexoraLauncher

## Требования

- Python 3.11 или новее. Java ставить не нужно: лаунчер скачает её сам.
- Интернет для загрузки игры и модов.

## Установка и запуск

```bash
git clone https://github.com/Atomfren/NexoraLauncher.git
cd Nex
python -m venv .venv
.venv\Scripts\activate          # Linux/macOS: source .venv/bin/activate
pip install -r requirements.txt
python main.py
```

Готовая сборка без Python: `python scripts/build.py` создаёт `dist/NexoraLauncher/NexoraLauncher.exe` и zip-архив рядом.

## Первые шаги

1. **Аккаунты** → «Офлайн-аккаунт» (любой ник) или «Войти через Microsoft». Для входа через Microsoft нужен Client ID, см. README.
2. **Инстансы** → «Создать»: выберите версию игры и загрузчик (например, Fabric). Установка начнётся сразу, прогресс виден внизу окна.
3. **Моды** → выберите инстанс → «Установить». Зависимости подтянутся автоматически.
4. **▶ Играть.**

Готовые сборки ставятся со страницы **Модпаки** — каждая становится отдельным инстансом. Также можно нажать **Импорт…** на странице инстансов и выбрать `.mrpack` или `.zip`.

## Параметры запуска

```bash
python main.py --debug                         # подробный лог
python main.py --self-test                     # проверка backend без окна (код 0 — успех)
python main.py --backend-url http://127.0.0.1:8000/api/v1 --token <токен>   # внешний backend
```

Переменная `NEXORA_HOME=<папка>` включает портативный режим: все данные хранятся в этой папке.

## Отдельный backend

```bash
set NEXORA_BACKEND_API_TOKEN=secret                 # Linux/macOS: export ...
python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
```

Без токена API открыт для всех локальных программ, и тогда доступна документация `/docs`. Используйте этот режим только для разработки.

## Где искать проблемы

- Логи лаунчера: **Настройки → Папки → Логи** (`frontend.log`, `backend.log`).
- Лог игры: **⚙ инстанса → Логи** или папка `logs` внутри инстанса.
- Если игра не запускается после смены версии или загрузчика: **⋯ → Проверить файлы игры**.

## Разработка

```bash
pip install -r requirements-dev.txt
ruff check .
pytest --cov
```
