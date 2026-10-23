"""Версия приложения (единый источник истины)."""

APP_NAME = "NexoraLauncher"
APP_ID = "nexoralauncher"
APP_VERSION = "1.5.0"
# Сайт лаунчера: на него ведёт логотип в углу окна
WEBSITE_URL = "https://nexoralauncher.ru"
USER_AGENT = f"Atomfren/{APP_NAME}/{APP_VERSION} (nexoralauncher.ru)"

# --- Канал обновлений ---------------------------------------------------------------------------
# Манифест выпуска (`latest.json`) и его подпись (`latest.json.sig`) лежат рядом на сайте.
# Первый адрес — свой сайт, второй — запасной: файлы, приложенные к последнему релизу GitHub.
UPDATE_MANIFEST_URLS = (
    "https://nexoralauncher.ru/downloads/latest.json",
    "https://github.com/Atomfren/NexoraLauncher/releases/latest/download/latest.json",
)

# Список языков, которые можно докачать, и подпись к нему — рядом, на том же сайте
LANGUAGE_INDEX_URLS = (
    "https://nexoralauncher.ru/languages/languages.json",
    "https://github.com/Atomfren/NexoraLauncher/releases/latest/download/languages.json",
)

# Открытый ключ Ed25519 (base64, 32 байта), которым проверяется подпись манифеста.
# Пара ключей создаётся командой ``python scripts/sign_release.py keygen``; закрытый ключ
# хранится только у выпускающего и в секрете CI, в репозиторий он не попадает.
# Пустая строка — канал не настроен: обновления не проверяются, в журнал пишется предупреждение.
UPDATE_PUBLIC_KEY = "6qH+lspH7tNlNpiyffdI9q+IMPiua9znrarhNY3edMU="
