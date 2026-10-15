> **Исторический документ.** Это ТЗ на разделение на backend/frontend (версия 0.x). Актуальное описание — в [README.md](README.md) и [CHANGELOG.md](CHANGELOG.md).

# Техническое Задание: Разделение NexoraLauncher на Backend и Frontend

## 1. Общие сведения

### 1.1 Назначение документа

Документ описывает архитектуру, требования и план миграции проекта QuantumLauncher на архитектуру с чётким разделением backend и frontend компонентов.

### 1.2 Цели разделения

| Цель | Описание |
|------|----------|
| **Независимость UI** | Возможность замены GUI-фреймворка без изменения backend логики |
| **Масштабируемость** | Backend можно масштабировать отдельно, добавлять новые клиенты |
| **Тестируемость** | Backend логику легко тестировать без GUI зависимостей |
| **Кроссплатформенность** | Один backend для Windows, Linux, macOS, Web, Mobile |
| **Микросервисная готовность** | Архитектура позволяет разделить backend на отдельные сервисы |

### 1.3 Ключевые принципы

1. **Backend = Stateless API сервис**
   - Только бизнес-логика и работа с данными
   - REST API / WebSocket / gRPC
   - Никаких зависимостей от GUI-фреймворков

2. **Frontend = Толстый клиент**
   - Только отображение и ввод пользователя
   - Обращается к backend через HTTP/WebSocket
   - Не имеет прямого доступа к backend логике

3. **Чёткие контракты через API**
   - Все взаимодействия через определённые endpoints
   - Pydantic модели для валидации
   - OpenAPI/Swagger документация

---

## 2. Текущая структура проекта

```
quantumlauncher/
├── main.py                 # Точка входа (GUI запуск)
├── __init__.py            # Версия пакета
├── __main__.py            # python -m запуск
├── ai/                    # AI ассистент (локальный)
│   └── assistant.py
├── api/                   # API клиенты (Modrinth, CurseForge)
│   ├── curseforge.py
│   └── modrinth.py
├── core/                  # Бизнес-логика
│   ├── auth.py           # Авторизация
│   ├── instance.py       # Управление инстансами
│   ├── minecraft.py      # Запуск Minecraft
│   ├── java_detector.py  # Детектор Java
│   ├── java_downloader.py
│   ├── jvm_flags.py
│   ├── pack_manager.py   # Импорт/экспорт
│   ├── server_manager.py
│   ├── server_ping.py
│   ├── crash_analyzer.py
│   ├── discord_rpc.py
│   └── skin.py
├── data/                  # БД слой
│   └── database.py       # SQLite (aiosqlite)
├── ui/                    # GUI (customtkinter)
│   ├── main_window.py
│   ├── styles.py
│   └── pages/            # 11 страниц
│       ├── home_page.py
│       ├── instances_page.py
│       ├── versions_page.py
│       ├── mods_page.py
│       ├── modpacks_page.py
│       ├── maps_page.py
│       ├── resourcepacks_page.py
│       ├── shaders_page.py
│       ├── servers_page.py
│       ├── ai_chat_page.py
│       └── settings_page.py
└── utils/                 # Утилиты
    ├── config.py         # Конфигурация
    ├── crypto.py         # Шифрование
    ├── i18n.py           # Локализация
    ├── paths.py          # Пути
    ├── perf.py
    └── _fastcore.pyx
```

---

## 3. Целевая архитектура

### 3.1 Общая схема

```
┌─────────────────────────────────────────────────────────────────┐
│                        QuantumLauncher                           │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │                    Backend (FastAPI)                     │   │
│  │  ┌─────────────┐  ┌─────────────┐  ┌─────────────────┐  │   │
│  │  │ REST API    │  │ WebSocket   │  │ Background      │  │   │
│  │  │ Endpoints   │  │ Endpoints   │  │ Tasks           │  │   │
│  │  └──────┬──────┘  └──────┬──────┘  └────────┬────────┘  │   │
│  │         │                │                   │           │   │
│  │  ┌──────▼────────────────▼───────────────────▼────────┐  │   │
│  │  │              Business Logic Layer                  │  │   │
│  │  │  ┌──────────┐  ┌──────────┐  ┌──────────────────┐ │  │   │
│  │  │  │ Instances│  │ Minecraft│  │   Auth           │ │  │   │
│  │  │  │ Manager  │  │ Manager  │  │   Manager        │ │  │   │
│  │  │  └──────────┘  └──────────┘  └──────────────────┘ │  │   │
│  │  └───────────────────────────────────────────────────────┘  │   │
│  │                            │                                 │   │
│  │  ┌─────────────────────────▼─────────────────────────────┐  │   │
│  │  │              Data Access Layer                         │  │   │
│  │  │  ┌────────────┐  ┌────────────┐  ┌────────────────┐   │  │   │
│  │  │  │  SQLite    │  │  Redis     │  │  External APIs │   │  │   │
│  │  │  │  (aiosqlite)│  │  (cache)   │  │  Modrinth/CF   │   │  │   │
│  │  │  └────────────┘  └────────────┘  └────────────────┘   │  │   │
│  │  └───────────────────────────────────────────────────────┘  │   │
│  └─────────────────────────────────────────────────────────────┘   │
│                              ▲                                      │
│                              │ HTTP / WebSocket                     │
│                              │                                      │
│  ┌───────────────────────────┴──────────────────────────────────┐  │
│  │                    Frontend (customtkinter)                   │  │
│  │  ┌─────────────┐  ┌─────────────┐  ┌─────────────────┐       │  │
│  │  │   Pages     │  │ Components  │  │  API Clients    │       │  │
│  │  │  (UI Screens)│  │  (Widgets)  │  │  (HTTP)         │       │  │
│  │  └─────────────┘  └─────────────┘  └─────────────────┘       │  │
│  └───────────────────────────────────────────────────────────────┘  │
│                                                                      │
│  ┌───────────────────────────────────────────────────────────────┐  │
│  │                      Shared Modules                            │  │
│  │  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────────┐  │  │
│  │  │  config  │  │  crypto  │  │   i18n   │  │    paths     │  │  │
│  │  └──────────┘  └──────────┘  └──────────┘  └──────────────┘  │  │
│  └───────────────────────────────────────────────────────────────┘  │
│                                                                      │
└──────────────────────────────────────────────────────────────────────┘
```

### 3.2 Структура директорий

```
quantumlauncher/
│
├── backend/                                    # 🔧 Backend сервис
│   ├── __init__.py
│   ├── main.py                                # FastAPI приложение, uvicorn entry
│   ├── config.py                              # Backend конфигурация
│   │
│   ├── api/                                   # API Endpoints
│   │   ├── __init__.py
│   │   ├── dependencies.py                    # Auth, DB сессии, зависимости
│   │   └── v1/                                # API v1
│   │       ├── __init__.py
│   │       ├── health.py                      # Health check
│   │       ├── instances.py                   # CRUD инстансов
│   │       ├── minecraft.py                   # Запуск, версии
│   │       ├── mods.py                        # Моды, поиск
│   │       ├── modpacks.py                    # Модпаки
│   │       ├── auth.py                        # Авторизация
│   │       ├── ai.py                          # AI чат (WebSocket)
│   │       ├── settings.py                    # Настройки
│   │       ├── servers.py                     # Сервера
│   │       ├── versions.py                    # Версии Minecraft
│   │       ├── maps.py                        # Карты
│   │       ├── resourcepacks.py               # Ресурспаки
│   │       └── shaders.py                     # Шейдеры
│   │
│   ├── core/                                  # Бизнес-логика (чистый Python)
│   │   ├── __init__.py
│   │   ├── auth.py                            # Авторизация (Offline, MS OAuth)
│   │   ├── instance.py                        # Управление инстансами
│   │   ├── minecraft.py                       # Запуск Minecraft
│   │   ├── java_detector.py                   # Детектор Java
│   │   ├── java_downloader.py                 # Загрузчик Java
│   │   ├── jvm_flags.py                       # JVM флаги
│   │   ├── pack_manager.py                    # Импорт/экспорт
│   │   ├── server_manager.py                  # Управление серверами
│   │   ├── server_ping.py                     # Ping серверов
│   │   ├── crash_analyzer.py                  # Анализ крашей
│   │   ├── discord_rpc.py                     # Discord RPC
│   │   ├── skin.py                            # Скины
│   │   └── java_detector.py                   # Детектор Java
│   │
│   ├── services/                              # Внешние API клиенты
│   │   ├── __init__.py
│   │   ├── modrinth.py                        # Modrinth API
│   │   ├── curseforge.py                      # CurseForge API
│   │   ├── ai_assistant.py                    # AI ассистент
│   │   └── microsoft.py                       # Microsoft OAuth
│   │
│   ├── db/                                    # Database слой
│   │   ├── __init__.py
│   │   ├── session.py                         # DB сессии
│   │   ├── models.py                          # SQLAlchemy/SQLModel модели
│   │   └── repository.py                      # Репозитории (CRUD)
│   │
│   └── models/                                # Pydantic DTO модели
│       ├── __init__.py
│       ├── instances.py                       # Instance DTO
│       ├── minecraft.py                       # Minecraft DTO
│       ├── mods.py                            # Mod DTO
│       ├── auth.py                            # Auth DTO
│       ├── ai.py                              # AI DTO
│       ├── settings.py                        # Settings DTO
│       └── servers.py                         # Server DTO
│
├── frontend/                                  # 🖥️ Frontend GUI
│   ├── __init__.py
│   ├── main.py                                # Точка входа GUI
│   ├── app.py                                 # Главное окно
│   ├── styles.py                              # Стили UI
│   │
│   ├── pages/                                 # Страницы приложения
│   │   ├── __init__.py
│   │   ├── home_page.py                       # Главная страница
│   │   ├── instances_page.py                  # Инстансы
│   │   ├── versions_page.py                   # Версии
│   │   ├── mods_page.py                       # Моды
│   │   ├── modpacks_page.py                   # Модпаки
│   │   ├── maps_page.py                       # Карты
│   │   ├── resourcepacks_page.py              # Ресурспаки
│   │   ├── shaders_page.py                    # Шейдеры
│   │   ├── servers_page.py                    # Сервера
│   │   ├── ai_chat_page.py                    # AI чат
│   │   └── settings_page.py                   # Настройки
│   │
│   ├── components/                            # UI компоненты
│   │   ├── __init__.py
│   │   ├── buttons.py                         # Кнопки
│   │   ├── dialogs.py                         # Диалоги
│   │   ├── cards.py                           # Карточки
│   │   ├── sidebar.py                         # Боковая панель
│   │   └── status_bar.py                      # Статус бар
│   │
│   ├── services/                              # API клиенты
│   │   ├── __init__.py
│   │   ├── api_client.py                      # Базовый HTTP клиент
│   │   ├── instances_api.py                   # Instances API
│   │   ├── minecraft_api.py                   # Minecraft API
│   │   ├── mods_api.py                        # Mods API
│   │   ├── auth_api.py                        # Auth API
│   │   ├── ai_api.py                          # AI API (WebSocket)
│   │   └── settings_api.py                    # Settings API
│   │
│   └── models/                                # DTO модели (Pydantic)
│       ├── __init__.py
│       ├── instances.py                       # Instance модель
│       └── minecraft.py                       # Minecraft модель
│
├── shared/                                    # 📦 Общие модули
│   ├── __init__.py
│   ├── config.py                              # Конфигурация приложения
│   ├── crypto.py                              # Шифрование токенов
│   ├── i18n.py                                # Локализация
│   ├── paths.py                               # Управление путями
│   └── models.py                              # Общие dataclass модели
│
├── quantumlauncher/                           # 📦 Главный пакет (для pip)
│   ├── __init__.py                            # Версия пакета
│   ├── __main__.py                            # python -m quantumlauncher
│   └── main.py                                # Единая точка входа
│
├── backend-requirements.txt                   # Зависимости backend
├── frontend-requirements.txt                  # Зависимости frontend
├── shared-requirements.txt                    # Зависимости shared
├── requirements.txt                           # Все зависимости (dev)
└── README.md                                  # Документация
```

---

## 4. API Контракты

### 4.1 REST Endpoints

#### 4.1.1 Health Check

```
GET /api/v1/health
Response:
{
  "status": "healthy",
  "version": "0.1.0",
  "timestamp": "2025-01-15T10:30:00Z"
}
```

#### 4.1.2 Instances

```
GET    /api/v1/instances/                    # Список всех инстансов
GET    /api/v1/instances/{name}              # Получить инстанс по имени
POST   /api/v1/instances/                    # Создать инстанс
PATCH  /api/v1/instances/{name}              # Обновить инстанс
DELETE /api/v1/instances/{name}              # Удалить инстанс
POST   /api/v1/instances/{name}/export       # Экспорт в .zip
POST   /api/v1/instances/import              # Импорт из .zip/.mrpack
```

#### 4.1.3 Minecraft

```
GET    /api/v1/minecraft/versions/available          # Доступные версии
GET    /api/v1/minecraft/versions/installed          # Установленные версии
POST   /api/v1/minecraft/versions/{version_id}/install   # Установить версию
POST   /api/v1/minecraft/versions/{version_id}/install_forge
POST   /api/v1/minecraft/versions/{version_id}/install_fabric
POST   /api/v1/minecraft/launch                          # Запустить Minecraft
GET    /api/v1/minecraft/status/{process_id}             # Статус процесса
DELETE /api/v1/minecraft/stop/{process_id}               # Остановить процесс
```

#### 4.1.4 Mods

```
GET    /api/v1/mods/search?query={q}&limit={n}     # Поиск модов
GET    /api/v1/mods/{project_id}                   # Получить мод
GET    /api/v1/mods/{project_id}/versions          # Версии мода
POST   /api/v1/mods/download                       # Скачать мод
GET    /api/v1/mods/installed                      # Установленные моды
POST   /api/v1/mods/install                        # Установить мод
DELETE /api/v1/mods/uninstall                      # Удалить мод
```

#### 4.1.5 Auth

```
POST   /api/v1/auth/offline/login                # Офлайн вход
POST   /api/v1/auth/microsoft/login/start        # Начать MS OAuth
POST   /api/v1/auth/microsoft/login/complete     # Завершить MS OAuth
POST   /api/v1/auth/microsoft/refresh            # Обновить токен
GET    /api/v1/auth/profile                      # Получить профиль
```

#### 4.1.6 Settings

```
GET    /api/v1/settings/                         # Получить настройки
PATCH  /api/v1/settings/                         # Обновить настройки
GET    /api/v1/settings/java/                    # Получить Java настройки
POST   /api/v1/settings/java/detect              # Автодетект Java
```

### 4.2 WebSocket Endpoints

```
WS     /api/v1/ai/chat                          # AI чат (streaming)
WS     /api/v1/minecraft/install/{version_id}   # Прогресс установки
```

---

## 5. Модели данных

### 5.1 Instance Model

```python
# backend/models/instances.py

from pydantic import BaseModel, Field
from datetime import datetime

class InstanceBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    version: str = Field(..., min_length=1)
    mod_loader: str = Field(default="vanilla", enum=["vanilla", "forge", "fabric", "quilt"])
    loader_version: str = ""

class InstanceCreate(InstanceBase):
    pass

class InstanceUpdate(BaseModel):
    version: str | None = None
    mod_loader: str | None = None
    loader_version: str | None = None
    java_path: str | None = None
    max_memory: int | None = Field(default=None, ge=512, le=65536)
    min_memory: int | None = Field(default=None, ge=256)
    width: int | None = Field(default=None, ge=800, le=3840)
    height: int | None = Field(default=None, ge=600, le=2160)
    fullscreen: bool | None = None

class InstanceResponse(InstanceBase):
    java_path: str
    max_memory: int
    min_memory: int
    width: int
    height: int
    fullscreen: bool
    created_at: str
    last_played: str | None = None
    play_count: int = 0

    class Config:
        from_attributes = True
```

### 5.2 Minecraft Launch Model

```python
# backend/models/minecraft.py

from pydantic import BaseModel, Field

class LaunchRequest(BaseModel):
    version_id: str = Field(..., min_length=1)
    username: str = Field(..., min_length=1, max_length=16)
    java_path: str = ""
    jvm_profile: str = Field(default="default", enum=["default", "performance", "low"])
    max_memory: int = Field(default=4096, ge=512, le=65536)
    min_memory: int = Field(default=512, ge=256)

class LaunchResponse(BaseModel):
    process_id: int
    version: str
    username: str
    status: str = "starting"

class VersionInfo(BaseModel):
    id: str
    type: str  # release, snapshot, addon
    release_time: str
```

### 5.3 Auth Model

```python
# backend/models/auth.py

from pydantic import BaseModel, Field

class OfflineLoginRequest(BaseModel):
    username: str = Field(..., min_length=1, max_length=16)

class UserProfile(BaseModel):
    username: str
    uuid: str
    auth_type: str  # "offline" | "microsoft"

class MicrosoftLoginStartResponse(BaseModel):
    url: str
    state: str
    code_verifier: str

class MicrosoftLoginCompleteRequest(BaseModel):
    client_id: str
    auth_code: str
    code_verifier: str
```

---

## 6. Технические требования

### 6.1 Backend

| Компонент | Технология | Версия | Обоснование |
|-----------|------------|--------|-------------|
| Web Framework | FastAPI | ^0.109.0 | Async-first, авто-документация |
| ASGI Server | Uvicorn | ^0.27.0 | Высокая производительность |
| HTTP Client | httpx | ^0.26.0 | Async HTTP для внешних API |
| Data Validation | Pydantic | ^2.5.0 | Валидация DTO |
| Database | aiosqlite | ^0.19.0 | Async SQLite |
| Background Tasks | BackgroundTasks | встроенно | Асинхронные задачи |
| WebSocket | FastAPI WebSocket | встроенно | Real-time коммуникация |
| Logging | loguru | ^0.7.0 | Удобное логирование |

### 6.2 Frontend

| Компонент | Технология | Версия | Обоснование |
|-----------|------------|--------|-------------|
| GUI Framework | PyQt6 | ^6.6.0 | Нативный, кроссплатформенный, профессиональный вид |
| HTTP Client | aiohttp | ^3.9.0 | Async HTTP для API |
| Image Processing | Pillow | ^10.2.0 | Обработка изображений |
| Logging | loguru | ^0.7.0 | Единое логирование |

### 6.3 Shared

| Компонент | Технология | Версия | Обоснование |
|-----------|------------|--------|-------------|
| Crypto | cryptography | ^42.0.0 | Шифрование токенов |
| Minecraft Lib | minecraft-launcher-lib | ^5.0.0 | Запуск Minecraft |

---

## 7. План миграции

### Этап 1: Подготовка инфраструктуры (1-2 дня)

**Задачи:**
1. Создать структуру директорий (backend/, frontend/, shared/)
2. Создать requirements.txt файлы
3. Создать shared модули (config, crypto, i18n, paths)
4. Настроить базовый FastAPI сервер с health check
5. Настроить единый запуск (quantumlauncher/main.py)

**Критерии готовности:**
- Backend запускается и отвечает на /api/v1/health
- Frontend может стартовать
- Shared модули доступны из обеих частей

### Этап 2: Миграция Core логики (3-5 дней)

**Задачи:**
1. Перенести `core/` в `backend/core/`
2. Обновить импорты на shared модули
3. Перенести `api/` в `backend/services/`
4. Перенести `data/database.py` в `backend/db/`
5. Добавить Pydantic модели в `backend/models/`

**Критерии готовности:**
- Все core функции работают через backend
- Нет циклических импортов
- Код тестируется unit-тестами

### Этап 3: Создание API Endpoints (5-7 дней)

**Задачи:**
1. Создать health endpoint
2. Создать instances CRUD endpoints
3. Создать minecraft launch endpoints
4. Создать mods endpoints
5. Создать auth endpoints
6. Создать settings endpoints
7. Создать WebSocket для AI чата

**Критерии готовности:**
- Все endpoints документированы (Swagger UI)
-Endpoints протестированы (Postman/pytest)
- Валидация запросов/ответов работает

### Этап 4: Миграция Frontend (5-7 дней)

**Задачи:**
1. Перенести `ui/` в `frontend/`
2. Заменить прямые вызовы core на API клиенты
3. Создать API клиент сервисы
4. Добавить обработку ошибок сети
5. Добавить loading states
6. Мигрировать страницы по одной

**Критерии готовности:**
- Frontend работает через HTTP API
- Все страницы отображаются корректно
- Ошибки сети обрабатываются
- Loading states показываются

### Этап 5: Интеграция и тестирование (2-3 дня)

**Задачи:**
1. Настроить единый запуск (backend + frontend)
2. Протестировать все пользовательские сценарии
3. Протестировать edge cases
4. Оптимизировать производительность
5. Написать интеграционные тесты

**Критерии готовности:**
- Приложение запускается одной командой
- Все функции работают корректно
- Нет критичных багов

### Этап 6: Документация и релиз (1-2 дня)

**Задачи:**
1. Обновить README.md
2. Создать API документацию
3. Создать ARCHITECTURE.md
4. Создать MIGRATION.md
5. Подготовить changelog

**Критерии готовности:**
- Документация полная и актуальная
- Читабельна для новых разработчиков

---

## 8. Критерии успеха

### Функциональные требования

| Требование | Критерий проверки |
|------------|-------------------|
| Backend независим от UI | Можно запустить backend без frontend |
| Frontend работает через API | Нет прямых импортов backend/core |
| Все функции мигрированы | 100% функций работает через API |
| API документация | Swagger UI доступен по /docs |
| Ошибки обрабатываются | Frontend показывает ошибки backend |

### Нефункциональные требования

| Требование | Критерий |
|------------|----------|
| Производительность | Ответ backend < 100ms для CRUD |
| Масштабируемость | Можно добавить новые клиенты |
| Тестируемость | Coverage > 70% для backend |
| Поддерживаемость | Чистый код, нет циклических импортов |

---

## 9. Риски и mitigation

| Риск | Вероятность | Влияние | Mitigation |
|------|-------------|---------|------------|
| API контракты меняются | Средняя | Высокое | Версионирование API (v1, v2) |
| Производительность HTTP | Низкая | Среднее | Кэширование, WebSocket для streaming |
| Сложность отладки | Средняя | Среднее | Логирование, OpenAPI docs |
| Миграция багов | Высокая | Низкое | Тщательное тестирование |
| Время миграции | Высокая | Среднее | Поэтапная миграция, параллельная работа |

---

## 10. Глоссарий

| Термин | Определение |
|--------|-------------|
| **Backend** | Серверная часть приложения, предоставляет API |
| **Frontend** | Клиентская часть приложения (GUI) |
| **API Contract** | Контракт между frontend и backend (endpoints, модели) |
| **DTO** | Data Transfer Object — модель для передачи данных |
| **Stateless** | Backend не хранит состояние сессии клиента |
| **WebSocket** | Протокол для двусторонней коммуникации в реальном времени |
| **Pydantic** | Библиотека для валидации данных в Python |
| **FastAPI** | Современный async веб-фреймворк для Python |

---

## 11. Контакты и поддержка

| Роль | Ответственный |
|------|---------------|
| Архитектор | NLP-Core-Team |
| Backend разработчик | atomfren |
| Frontend разработчик | atomfren |
| Документация | atomfren |

---

## 12. Приложения

### Приложение A: Пример FastAPI приложения

```python
# backend/main.py

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.api.v1 import health, instances, minecraft, mods, auth, ai, settings

app = FastAPI(
    title="QuantumLauncher Backend API",
    version="0.1.0",
    description="Backend API для QuantumLauncher",
)

# CORS middleware (для будущих веб-клиентов)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Подключение router'ов
app.include_router(health.router, prefix="/api/v1")
app.include_router(instances.router, prefix="/api/v1")
app.include_router(minecraft.router, prefix="/api/v1")
app.include_router(mods.router, prefix="/api/v1")
app.include_router(auth.router, prefix="/api/v1")
app.include_router(ai.router, prefix="/api/v1")
app.include_router(settings.router, prefix="/api/v1")

@app.get("/")
async def root():
    return {"message": "QuantumLauncher Backend API"}
```

### Приложение B: Пример Frontend API Client

```python
# frontend/services/api_client.py

import aiohttp
from typing import Any

class APIClient:
    def __init__(self, base_url: str = "http://localhost:8000/api/v1"):
        self.base_url = base_url
        self._session: aiohttp.ClientSession | None = None
    
    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session
    
    async def get(self, endpoint: str, **kwargs) -> dict[str, Any]:
        session = await self._get_session()
        async with session.get(f"{self.base_url}{endpoint}", **kwargs) as resp:
            resp.raise_for_status()
            return await resp.json()
    
    async def post(self, endpoint: str, **kwargs) -> dict[str, Any]:
        session = await self._get_session()
        async with session.post(f"{self.base_url}{endpoint}", **kwargs) as resp:
            resp.raise_for_status()
            return await resp.json()
    
    async def close(self):
        if self._session and not self._session.closed:
            await self._session.close()
```

---

## 13. История версий документа

| Версия | Дата | Автор | Изменения |
|--------|------|-------|-----------|
| 0.1.0 | 2025-01-15 | NLP-Core-Team | Начальная версия |

---

**Утверждено:**

Архитектор: ___________________ / NLP-Core-Team / Дата: __________

Разработчик: ___________________ / atomfren / Дата: __________
