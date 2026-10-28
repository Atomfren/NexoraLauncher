"""Бюджет запуска: слой интерфейса не должен тянуть за собой backend.

Окно открывается за полторы секунды только потому, что интерфейс не ждёт backend —
тот поднимается в отдельном потоке (`frontend/backend_runner.py`). Достаточно одного
неосторожного импорта в QML-слое, чтобы при запуске загружался весь backend с его
зависимостями, и секунды вернутся. Глазами такую правку не поймать: окно всё равно
откроется, просто позже, — поэтому список импортов проверяется тестом.

Замер делается в отдельном процессе: в общем процессе pytest нужные модули уже
загружены другими тестами, и измерять там нечего.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

# Что интерфейсу позволено загрузить при старте:
# errors — классы ошибок, на них смотрит клиент API;
# instance — `folder_for_title` для мастера создания сборки.
ALLOWED_BACKEND = {"backend", "backend.core", "backend.core.errors", "backend.core.instance"}

# Потолок на импорт QML-слоя. Не норматив, а предохранитель: сюда входит сам PySide6,
# на холодной машине CI это несколько секунд. Если упёрлись — что-то тяжёлое загружается зря.
IMPORT_CEILING_SECONDS = 12.0

PROBE = """
import json, sys, time
start = time.perf_counter()
import frontend.quick.app  # noqa: F401 — проверяем побочный эффект импорта
print(json.dumps({"elapsed": time.perf_counter() - start,
                  "backend": sorted(m for m in sys.modules if m.startswith("backend"))}))
"""


@pytest.fixture(scope="module")
def probe() -> dict:
    pytest.importorskip("PySide6.QtQuick")
    done = subprocess.run([sys.executable, "-c", PROBE], cwd=ROOT, text=True,
                          capture_output=True, timeout=180,
                          env={**os.environ, "PYTHONPATH": str(ROOT),
                               "QT_QPA_PLATFORM": "offscreen"})
    assert done.returncode == 0, f"импорт интерфейса не прошёл:\n{done.stderr[-2000:]}"
    return json.loads(done.stdout.strip().splitlines()[-1])


def test_ui_does_not_import_the_backend(probe):
    extra = set(probe["backend"]) - ALLOWED_BACKEND
    assert not extra, (
        "при запуске загружается backend, которого не должно быть в этот момент: "
        f"{', '.join(sorted(extra))}. Перенесите импорт внутрь функции, которая им пользуется, "
        "или в поток backend — иначе окно начнёт ждать его загрузки."
    )


def test_ui_import_stays_within_the_ceiling(probe):
    assert probe["elapsed"] < IMPORT_CEILING_SECONDS, (
        f"импорт слоя интерфейса занял {probe['elapsed']:.1f} с при потолке "
        f"{IMPORT_CEILING_SECONDS:.0f} с — окно открывается тем позже"
    )
