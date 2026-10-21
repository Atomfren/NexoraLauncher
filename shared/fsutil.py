"""Безопасная работа с файлами (shared)."""

import json
import os
import re
import tempfile
import zipfile
from pathlib import Path
from typing import Any

_RESERVED_WINDOWS = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}
_NAME_RE = re.compile(r"^[\w\-. ()\[\]!+'&,]+$", re.UNICODE)


class UnsafePathError(ValueError):
    """Путь выходит за пределы разрешённой директории или имя недопустимо."""


def validate_name(name: str, max_length: int = 64) -> str:
    """Проверяет имя, используемое как имя папки (инстанс, мир).

    Запрещены разделители путей, ``..``, управляющие символы,
    зарезервированные имена Windows и пробелы/точки по краям.
    """
    if not isinstance(name, str):
        raise UnsafePathError("Имя должно быть строкой")
    if not name or len(name) > max_length:
        raise UnsafePathError(f"Имя должно содержать от 1 до {max_length} символов")
    if name != name.strip() or name.endswith("."):
        raise UnsafePathError("Имя не может начинаться/заканчиваться пробелом или точкой")
    if name in (".", "..") or not _NAME_RE.match(name):
        raise UnsafePathError(f"Недопустимые символы в имени: {name!r}")
    if name.split(".")[0].upper() in _RESERVED_WINDOWS:
        raise UnsafePathError(f"Зарезервированное имя: {name!r}")
    return name


def sanitize_name(name: str, fallback: str = "Instance", max_length: int = 48) -> str:
    """Превращает произвольную строку (например, название модпака) в допустимое имя."""
    cleaned = "".join(ch if _NAME_RE.match(ch) else "_" for ch in (name or ""))
    cleaned = cleaned.strip(" .")[:max_length].strip(" .")
    try:
        return validate_name(cleaned)
    except UnsafePathError:
        return fallback


def safe_join(base: Path, *parts: str) -> Path:
    """Соединяет пути и гарантирует, что результат лежит внутри ``base``."""
    base_resolved = base.resolve()
    target = base_resolved.joinpath(*parts).resolve()
    if target != base_resolved and base_resolved not in target.parents:
        raise UnsafePathError(f"Путь выходит за пределы {base}")
    return target


def safe_extract_zip(zf: zipfile.ZipFile, dest: Path, strip_prefix: str = "") -> list[Path]:
    """Распаковывает архив с защитой от zip-slip.

    Если задан ``strip_prefix``, извлекаются только записи с этим префиксом,
    а сам префикс отбрасывается.
    """
    dest.mkdir(parents=True, exist_ok=True)
    extracted: list[Path] = []
    for info in zf.infolist():
        name = info.filename.replace("\\", "/")
        if strip_prefix:
            if not name.startswith(strip_prefix):
                continue
            name = name[len(strip_prefix):]
        if not name or name.endswith("/"):
            continue
        target = safe_join(dest, *name.split("/"))
        target.parent.mkdir(parents=True, exist_ok=True)
        with zf.open(info) as src, open(target, "wb") as dst:
            while chunk := src.read(1024 * 1024):
                dst.write(chunk)
        extracted.append(target)
    return extracted


def atomic_write_text(path: Path, text: str) -> None:
    """Атомарно записывает текст: временный файл + os.replace."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def atomic_write_json(path: Path, data: Any) -> None:
    """Атомарно записывает JSON."""
    atomic_write_text(path, json.dumps(data, indent=2, ensure_ascii=False))


def read_json(path: Path, default: Any = None) -> Any:
    """Читает JSON, возвращая ``default`` при отсутствии/повреждении файла."""
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def dir_size(path: Path) -> int:
    """Суммарный размер файлов в директории."""
    total = 0
    for p in path.rglob("*"):
        try:
            if p.is_file():
                total += p.stat().st_size
        except OSError:
            pass
    return total


def remove_tree(path: Path, attempts: int = 5) -> None:
    """``shutil.rmtree``, устойчивый к Windows: снимает «только чтение» и повторяет попытку.

    Антивирус и индексатор ненадолго открывают свежие файлы — из-за этого удаление
    иногда падает с «Отказано в доступе», хотя через долю секунды проходит.
    """
    import shutil
    import stat
    import sys
    import time

    def retry_writable(func, target, _exc) -> None:
        try:
            os.chmod(target, stat.S_IWRITE)
            func(target)
        except FileNotFoundError:
            pass

    for attempt in range(attempts):
        try:
            if sys.version_info >= (3, 12):
                shutil.rmtree(path, onexc=retry_writable)
            else:
                shutil.rmtree(path, onerror=retry_writable)
            return
        except FileNotFoundError:
            return
        except OSError:
            if attempt == attempts - 1:
                raise
            time.sleep(0.25 * (attempt + 1))


def processes_using(path: Path) -> list[str]:
    """Процессы, в командной строке которых есть этот путь (обычно — запущенная игра). Только Windows."""
    import subprocess
    import sys
    if sys.platform != "win32":
        return []
    needle = str(path).replace("'", "''")
    script = ("Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -and "
              f"$_.CommandLine.IndexOf('{needle}', [StringComparison]::OrdinalIgnoreCase) -ge 0 }} | "
              "ForEach-Object { \"$($_.Name) (PID $($_.ProcessId))\" }")
    try:
        out = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
                             capture_output=True, text=True, timeout=15,
                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except (OSError, subprocess.SubprocessError):
        return []
    return [line.strip() for line in out.stdout.splitlines() if line.strip() and "powershell" not in line.lower()]
