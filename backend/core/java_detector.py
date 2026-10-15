"""Детектор установленных Java."""

import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from loguru import logger

from shared.paths import get_minecraft_dir

_EXE = "java.exe" if os.name == "nt" else "java"
_VERSION_RE = re.compile(r'version "([^"]+)"')
_VENDOR_HINTS = (
    ("Temurin", "Eclipse Temurin"), ("Zulu", "Azul Zulu"), ("Corretto", "Amazon Corretto"),
    ("Microsoft", "Microsoft"), ("GraalVM", "GraalVM"), ("Semeru", "IBM Semeru"),
    ("Liberica", "BellSoft Liberica"), ("Mojang", "Mojang"), ("OpenJDK", "OpenJDK"),
    ("Java(TM)", "Oracle"),
)


@dataclass
class JavaInfo:
    """Информация о Java."""

    path: str
    version: str
    major: int
    vendor: str
    is_64bit: bool = True


def parse_major(version: str) -> int:
    """Извлекает мажорную версию: '1.8.0_381' → 8, '17.0.2' → 17, '21' → 21."""
    match = re.match(r"(\d+)(?:\.(\d+))?", version or "")
    if not match:
        return 0
    first = int(match.group(1))
    if first == 1 and match.group(2):
        return int(match.group(2))
    return first


def probe_java(java_path: Path | str) -> JavaInfo | None:
    """Запускает ``java -version`` и разбирает вывод."""
    try:
        kwargs = {}
        if os.name == "nt":
            kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
        result = subprocess.run(
            [str(java_path), "-version"], capture_output=True, text=True, timeout=8,
            encoding="utf-8", errors="replace", **kwargs,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    output = (result.stderr or "") + (result.stdout or "")
    match = _VERSION_RE.search(output)
    if not match:
        return None
    version = match.group(1)
    vendor = "Unknown"
    for hint, name in _VENDOR_HINTS:
        if hint.lower() in output.lower() or hint.lower() in str(java_path).lower():
            vendor = name
            break
    return JavaInfo(path=str(java_path), version=version, major=parse_major(version),
                    vendor=vendor, is_64bit="64-Bit" in output)


def _candidate_paths() -> list[Path]:
    candidates: list[Path] = []

    def add_bin(home: Path) -> None:
        exe = home / "bin" / _EXE
        if exe.exists():
            candidates.append(exe)

    # Рантаймы, скачанные лаунчером (Mojang)
    runtime = get_minecraft_dir() / "runtime"
    if runtime.exists():
        candidates.extend(runtime.rglob(_EXE))

    if java_home := os.environ.get("JAVA_HOME"):
        add_bin(Path(java_home))
    if in_path := shutil.which("java"):
        candidates.append(Path(in_path))

    roots: list[Path] = []
    if os.name == "nt":
        for env in ("PROGRAMFILES", "PROGRAMFILES(X86)", "PROGRAMW6432"):
            if value := os.environ.get(env):
                roots.append(Path(value))
        roots.append(Path.home() / ".jdks")
        vendor_dirs = ("Java", "Eclipse Adoptium", "Eclipse Foundation", "Zulu", "Microsoft",
                       "BellSoft", "Amazon Corretto", "Semeru", "AdoptOpenJDK", "GraalVM")
        for root in roots:
            for vendor in vendor_dirs:
                base = root / vendor
                if base.is_dir():
                    for home in base.iterdir():
                        add_bin(home)
            if root.name == ".jdks" and root.is_dir():
                for home in root.iterdir():
                    add_bin(home)
    else:
        for base in (Path("/usr/lib/jvm"), Path("/usr/java"), Path("/opt"),
                     Path("/Library/Java/JavaVirtualMachines"),
                     Path.home() / ".sdkman" / "candidates" / "java", Path.home() / ".jdks"):
            if base.is_dir():
                for home in base.iterdir():
                    add_bin(home)
                    add_bin(home / "Contents" / "Home")
    return candidates


def find_java_installations() -> list[JavaInfo]:
    """Находит все установки Java, отсортированные по убыванию версии."""
    seen: set[str] = set()
    results: list[JavaInfo] = []
    for path in _candidate_paths():
        try:
            key = str(path.resolve()).lower()
        except OSError:
            continue
        if key in seen:
            continue
        seen.add(key)
        if info := probe_java(path):
            results.append(info)
    logger.info(f"Найдено Java: {len(results)}")
    return sorted(results, key=lambda j: (j.major, j.version), reverse=True)


def find_best_java(min_version: int = 17, max_version: int | None = None) -> JavaInfo | None:
    """Подбирает Java в заданном диапазоне мажорных версий (самую свежую)."""
    for java in find_java_installations():
        if java.major >= min_version and (max_version is None or java.major <= max_version):
            return java
    return None
