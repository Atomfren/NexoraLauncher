"""Выбор видеокарты для игры.

На ноутбуках с двумя видеокартами Windows по умолчанию запускает Java на встроенной графике —
игра идёт в разы медленнее, чем могла бы. Переключить её можно через системные «Настройки
графики»: Windows хранит выбор пользователя в реестре, по одной записи на программу::

    HKCU\\Software\\Microsoft\\DirectX\\UserGpuPreferences
    "C:\\...\\javaw.exe" = "GpuPreference=2;"      2 — высокая производительность (дискретная)
                                                   1 — энергосбережение (встроенная)

Мы пишем ровно ту же запись, что и окно настроек Windows: только для текущего пользователя,
без прав администратора, обратимо. Никаких драйверов и сторонних утилит.

Запись действует на конкретный файл ``java.exe``/``javaw.exe``, поэтому применяется перед
каждым запуском: Java у разных сборок может быть разной.
"""

import os
import re
import subprocess
from dataclasses import dataclass, field

from loguru import logger

PREFERENCE_KEY = r"Software\Microsoft\DirectX\UserGpuPreferences"
HIGH_PERFORMANCE = "2"
POWER_SAVING = "1"

# Выбор пользователя в настройках лаунчера
AUTO = "auto"          # дискретная, если она есть
DISCRETE = "discrete"  # всегда дискретная
INTEGRATED = "integrated"  # всегда встроенная
SYSTEM = "system"      # не вмешиваться, оставить решение Windows
CHOICES = (AUTO, DISCRETE, INTEGRATED, SYSTEM)

# Название — единственное, по чему можно отличить видеокарты, поэтому разбираем его аккуратно.
# Intel Arc бывает и дискретной (Arc A770), и встроенной («Intel Arc Graphics» без модели),
# поэтому дискретной считаем только версию с номером модели.
_DISCRETE_PATTERNS = (r"geforce", r"\brtx\b", r"\bgtx\b", r"quadro", r"radeon\s*(?:\(tm\)\s*)?rx\b",
                      r"radeon\s*pro\b", r"arc\W*(?:\(tm\)\W*)?[ab]\d{3}", r"firepro", r"\btitan\b",
                      r"\bnvidia\b")
_INTEGRATED_PATTERNS = (r"uhd graphics", r"\bhd graphics", r"\biris\b", r"vega \d+ graphics",
                        r"radeon\s*(?:\(tm\)\s*)?graphics", r"integrated", r"microsoft basic",
                        r"parallels", r"vmware", r"virtualbox", r"\bllvmpipe\b")


@dataclass
class Adapter:
    """Видеокарта, как её видит система."""

    name: str
    discrete: bool

    def to_dict(self) -> dict:
        return {"name": self.name, "discrete": self.discrete}


@dataclass
class GpuState:
    """Что есть в системе и что сейчас выбрано."""

    supported: bool = False
    adapters: list[Adapter] = field(default_factory=list)
    preference: str = AUTO

    @property
    def discrete(self) -> Adapter | None:
        return next((a for a in self.adapters if a.discrete), None)

    def to_dict(self) -> dict:
        discrete = self.discrete
        return {"supported": self.supported, "preference": self.preference,
                "adapters": [a.to_dict() for a in self.adapters],
                "discrete_name": discrete.name if discrete else ""}


def classify(name: str) -> bool:
    """Дискретная ли видеокарта по её названию.

    Надёжного признака в системе нет, поэтому решаем по названию. Спорные случаи
    (AMD «Radeon Graphics» внутри процессора, Intel Iris) считаем встроенными:
    лучше не трогать запуск, чем отправить игру на несуществующую видеокарту.
    """
    low = name.lower()
    if any(re.search(pattern, low) for pattern in _INTEGRATED_PATTERNS):
        return False
    return any(re.search(pattern, low) for pattern in _DISCRETE_PATTERNS)


def _query_adapters_windows() -> list[str]:
    """Названия видеокарт из WMI. Пустой список — определить не удалось."""
    command = ["powershell", "-NoProfile", "-NonInteractive", "-Command",
               "(Get-CimInstance Win32_VideoController).Name"]
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=20,
                                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except (OSError, subprocess.SubprocessError) as e:
        logger.debug(f"Не удалось получить список видеокарт: {e}")
        return []
    if result.returncode != 0:
        logger.debug(f"Список видеокарт: PowerShell вернул {result.returncode}")
        return []
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def list_adapters() -> list[Adapter]:
    """Видеокарты системы. На других ОС — пусто."""
    if os.name != "nt":
        return []
    seen: dict[str, Adapter] = {}
    for name in _query_adapters_windows():
        if name not in seen:
            seen[name] = Adapter(name=name, discrete=classify(name))
    return list(seen.values())


def is_supported() -> bool:
    """Переключение доступно только там, где его понимает система."""
    return os.name == "nt"


def read_preference(exe_path: str) -> str:
    """Что сейчас записано в Windows для этой программы: ``2``, ``1`` или пустая строка."""
    if not is_supported():
        return ""
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, PREFERENCE_KEY) as key:
            value, _ = winreg.QueryValueEx(key, exe_path)
    except OSError:
        return ""
    found = re.search(r"GpuPreference=(\d)", str(value))
    return found.group(1) if found else ""


def apply_preference(exe_path: str, preference: str, adapters: list[Adapter] | None = None) -> str:
    """Записывает выбор видеокарты для программы. Возвращает то, что получилось.

    ``system`` убирает нашу запись и возвращает решение Windows. Если дискретной видеокарты
    нет, при ``auto`` ничего не пишется — на одной видеокарте выбор бессмыслен.
    """
    if not is_supported() or not exe_path:
        return ""
    if preference not in CHOICES:
        preference = AUTO
    if preference == AUTO:
        pool = list_adapters() if adapters is None else adapters
        if not any(a.discrete for a in pool):
            return ""
        wanted = HIGH_PERFORMANCE
    elif preference == DISCRETE:
        wanted = HIGH_PERFORMANCE
    elif preference == INTEGRATED:
        wanted = POWER_SAVING
    else:
        _clear_preference(exe_path)
        return ""

    if not _write_preference(exe_path, wanted):
        return ""
    logger.info(f"Видеокарта для {exe_path}: "
                f"{'дискретная' if wanted == HIGH_PERFORMANCE else 'встроенная'} (настройка «{preference}»)")
    return wanted


def _write_preference(exe_path: str, value: str) -> bool:
    import winreg

    try:
        with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, PREFERENCE_KEY, 0, winreg.KEY_SET_VALUE) as key:
            winreg.SetValueEx(key, exe_path, 0, winreg.REG_SZ, f"GpuPreference={value};")
    except OSError as e:
        logger.warning(f"Не удалось выбрать видеокарту для {exe_path}: {e}")
        return False
    return True


def _clear_preference(exe_path: str) -> None:
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, PREFERENCE_KEY, 0, winreg.KEY_SET_VALUE) as key:
            winreg.DeleteValue(key, exe_path)
    except OSError:
        pass  # записи и не было


def state(preference: str = AUTO) -> GpuState:
    """Сводка для интерфейса: есть ли выбор, какие видеокарты, что выбрано."""
    return GpuState(supported=is_supported(), adapters=list_adapters(),
                    preference=preference if preference in CHOICES else AUTO)
