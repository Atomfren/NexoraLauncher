"""Сборка дистрибутива NexoraLauncher через PyInstaller.

Запуск из корня проекта::

    pip install -r requirements-dev.txt
    python scripts/build.py

Результат — папка ``dist/NexoraLauncher`` и архив ``dist/NexoraLauncher-<версия>-<платформа>.zip``.
С флагом ``--installer`` (Windows, нужен Inno Setup 6) — ещё и ``dist/NexoraLauncher-<версия>-setup.exe``.
"""

import argparse
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from shared.version import APP_VERSION  # noqa: E402


def find_iscc() -> Path | None:
    """Компилятор Inno Setup: из PATH или из стандартных мест установки."""
    found = shutil.which("ISCC") or shutil.which("iscc")
    if found:
        return Path(found)
    places = [(os.environ.get("LOCALAPPDATA"), "Programs"), (os.environ.get("ProgramFiles(x86)"), ""),
              (os.environ.get("ProgramFiles"), "")]
    for base, sub in places:
        candidate = Path(base or "") / sub / "Inno Setup 6" / "ISCC.exe"
        if base and candidate.exists():
            return candidate
    return None


def build_installer() -> Path:
    iscc = find_iscc()
    if iscc is None:
        raise SystemExit("Не найден Inno Setup 6 (ISCC.exe). Установите: winget install JRSoftware.InnoSetup")
    subprocess.run([str(iscc), f"/DAppVersion={APP_VERSION}", "/Qp", str(ROOT / "installer" / "nexora.iss")],
                   cwd=ROOT, check=True)
    return ROOT / "dist" / f"NexoraLauncher-{APP_VERSION}-setup.exe"


def precompile_qml(dist: Path) -> None:
    """Компилирует QML в байт-код рядом с исходниками в сборке.

    Иначе Qt разбирает 64 файла при первом запуске у каждого пользователя — это около
    полусекунды и 2 МБ в его кэше. Компилируем уже разложенные файлы: кэш проверяется
    по самому файлу, поэтому делать это до копирования нельзя.

    Если компилятора нет или он споткнулся — не беда: Qt просто разберёт QML сам.
    """
    qml_dir = next((p for p in dist.rglob("qml") if (p / "Main.qml").exists()), None)
    if qml_dir is None:
        print("QML в сборке не найден — пропускаю прекомпиляцию")
        return
    tool = Path(sys.executable).parent / ("pyside6-qmlcachegen.exe" if os.name == "nt" else "pyside6-qmlcachegen")
    if not tool.exists():
        print("pyside6-qmlcachegen не найден — QML будет разбираться при первом запуске")
        return
    done, failed = 0, 0
    for source in sorted(qml_dir.rglob("*.qml")):
        result = subprocess.run([str(tool), "-I", str(qml_dir), str(source), "-o", f"{source}c"],
                                capture_output=True)
        if result.returncode == 0 and Path(f"{source}c").exists():
            done += 1
        else:
            failed += 1
    print(f"QML скомпилирован: {done} файлов" + (f", не вышло: {failed}" if failed else ""))


def main() -> int:
    parser = argparse.ArgumentParser(description="Сборка NexoraLauncher")
    parser.add_argument("--installer", action="store_true", help="собрать и установщик (Inno Setup 6)")
    args = parser.parse_args()
    # Консоль CI на Windows — cp1252: без этого русский вывод роняет готовую сборку
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if not (ROOT / "resources" / "icon.ico").exists():
        subprocess.run([sys.executable, str(ROOT / "scripts" / "make_icon.py")], check=True)
    subprocess.run([sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "nexoralauncher.spec"],
                   cwd=ROOT, check=True)
    dist = ROOT / "dist" / "NexoraLauncher"
    precompile_qml(dist)
    system = {"Windows": "windows", "Darwin": "macos"}.get(platform.system(), "linux")
    archive = ROOT / "dist" / f"NexoraLauncher-{APP_VERSION}-{system}-{platform.machine().lower()}"
    shutil.make_archive(str(archive), "zip", dist.parent, dist.name)
    print(f"Готово: {dist}\nАрхив: {archive}.zip")
    if args.installer:
        print(f"Установщик: {build_installer()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
