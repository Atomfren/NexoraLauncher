# -*- mode: python ; coding: utf-8 -*-
# Сборка: pyinstaller nexoralauncher.spec  (или scripts/build.py)
# Результат: dist/NexoraLauncher/NexoraLauncher(.exe)

import sys

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

hiddenimports = (
    collect_submodules("backend")
    + collect_submodules("frontend")
    + collect_submodules("uvicorn")
    + collect_submodules("minecraft_launcher_lib")
)
datas = ([("resources", "resources"), ("frontend/quick/qml", "frontend/quick/qml")]
         + collect_data_files("minecraft_launcher_lib"))

a = Analysis(
    ["main.py"],
    pathex=["."],
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=["tkinter", "pytest", "llama_cpp", "PyQt6.QtWebEngineCore", "PyQt6.QtQuick3D",
              "PyQt6.QtMultimedia", "PyQt6.Qt3DCore", "PyQt6.QtBluetooth"],
    noarchive=False,
)
# Модули Qt, которые интерфейс не использует (3D, мультимедиа, датчики…): −40 МБ в сборке
_UNUSED_QT = ("Quick3D", "Multimedia", "Positioning", "RemoteObjects", "Sensors", "TextToSpeech", "WebChannel",
              "WebSockets", "Pdf", "QuickTest", "Qt6Test", "qml/QtTest", "SpatialAudio")


def _used(entry) -> bool:
    return not any(key in entry[0].replace("\\", "/") for key in _UNUSED_QT)


a.binaries = [b for b in a.binaries if _used(b)]
a.datas = [d for d in a.datas if _used(d)]

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="NexoraLauncher",
    console=False,
    icon="resources/icon.ico" if sys.platform == "win32" else None,
)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="NexoraLauncher")

if sys.platform == "darwin":
    app = BUNDLE(coll, name="NexoraLauncher.app", icon=None, bundle_identifier="com.atomfren.nexoralauncher")
