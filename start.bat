@echo off
rem Запуск NexoraLauncher: при первом запуске создаёт .venv и ставит зависимости
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    echo Первый запуск: создаю окружение и ставлю зависимости...
    py -3.12 -m venv .venv || python -m venv .venv
    ".venv\Scripts\python.exe" -m pip install --upgrade pip
    ".venv\Scripts\python.exe" -m pip install -r requirements.txt
)
start "" ".venv\Scripts\pythonw.exe" main.py %*
