"""Ключи и подпись манифеста обновлений.

Один раз — создать пару ключей::

    python scripts/sign_release.py keygen --out release_key.pem

Закрытый ключ (``release_key.pem``) хранится только у выпускающего: в репозиторий он не попадает
(исключён в .gitignore), для CI кладётся в секрет ``NEXORA_RELEASE_KEY`` целиком, текстом.
Открытый ключ печатается строкой, которую нужно вписать в ``shared/version.py``
(``UPDATE_PUBLIC_KEY``) — именно он вшивается в сборку и проверяет подпись.

Перед каждым выпуском — собрать и подписать манифест::

    python scripts/sign_release.py sign dist --version 1.5.1 --notes CHANGELOG.md --key release_key.pem

Рядом с архивом появятся ``latest.json`` и ``latest.json.sig``; оба файла выкладываются
на сайт (в ``downloads/``) и прикладываются к релизу GitHub. Проверить подпись::

    python scripts/sign_release.py verify dist/latest.json
"""

import argparse
import base64
import hashlib
import json
import os
import sys
from datetime import date
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from shared.version import APP_NAME, APP_VERSION, UPDATE_PUBLIC_KEY  # noqa: E402

MANIFEST_NAME = "latest.json"
SIGNATURE_NAME = MANIFEST_NAME + ".sig"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as file:
        for chunk in iter(lambda: file.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_private_key(source: str | None) -> Ed25519PrivateKey:
    """Закрытый ключ из файла, из ``--key`` или из переменной ``NEXORA_RELEASE_KEY`` (для CI)."""
    material = os.environ.get("NEXORA_RELEASE_KEY", "")
    if source:
        material = Path(source).read_text(encoding="utf-8")
    if not material.strip():
        raise SystemExit("Нет закрытого ключа: укажите --key или переменную NEXORA_RELEASE_KEY")
    key = serialization.load_pem_private_key(material.encode("utf-8"), password=None)
    if not isinstance(key, Ed25519PrivateKey):
        raise SystemExit("Нужен ключ Ed25519")
    return key


def public_key_line(key: Ed25519PublicKey) -> str:
    raw = key.public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    return f'UPDATE_PUBLIC_KEY = "{base64.b64encode(raw).decode("ascii")}"'


def cmd_keygen(args: argparse.Namespace) -> None:
    out = Path(args.out)
    if out.exists() and not args.force:
        raise SystemExit(f"{out} уже существует — старый ключ перезаписывать нельзя (--force, если точно нужно)")
    key = Ed25519PrivateKey.generate()
    pem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                            serialization.NoEncryption())
    out.write_bytes(pem)
    if os.name != "nt":
        out.chmod(0o600)
    print(f"Закрытый ключ: {out} — храните его вне репозитория и сделайте копию.")
    print("Потеря ключа означает, что обновления перестанут приниматься установленными лаунчерами.")
    print("\nВпишите в shared/version.py:\n")
    print(public_key_line(key.public_key()))


def cmd_sign(args: argparse.Namespace) -> None:
    dist = Path(args.dist).resolve()
    version = args.version or APP_VERSION
    key = load_private_key(args.key)

    files: dict[str, dict[str, object]] = {}
    for kind, name in (("setup", f"{APP_NAME}-{version}-setup.exe"),
                       ("zip", f"{APP_NAME}-{version}-windows-amd64.zip")):
        path = dist / name
        if not path.is_file():
            if kind == "zip":
                raise SystemExit(f"Нет архива {path} — он обязателен для автообновления")
            print(f"Установщик не найден ({name}) — манифест будет только с архивом")
            continue
        files[kind] = {"file": name, "size": path.stat().st_size, "sha256": sha256(path)}
        print(f"{name}: {path.stat().st_size / 1048576:.1f} МБ")

    notes = ""
    if args.notes:
        notes = Path(args.notes).read_text(encoding="utf-8").strip()[:4000]

    manifest = {"version": version, "date": date.today().isoformat(), **files}
    if notes:
        manifest["notes"] = notes
    if args.page:
        manifest["page"] = args.page
    raw = (json.dumps(manifest, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    signature = base64.b64encode(key.sign(raw)).decode("ascii")

    (dist / MANIFEST_NAME).write_bytes(raw)
    (dist / SIGNATURE_NAME).write_text(signature + "\n", encoding="utf-8")
    print(f"\n{dist / MANIFEST_NAME}\n{dist / SIGNATURE_NAME}")

    expected = public_key_line(key.public_key())
    if expected.split('"')[1] != UPDATE_PUBLIC_KEY:
        print("\nВНИМАНИЕ: открытый ключ в shared/version.py не от этого ключа —"
              " собранные лаунчеры такой манифест отклонят. Нужная строка:\n")
        print(expected)


def cmd_verify(args: argparse.Namespace) -> None:
    """Проверяет подпись тем же кодом и тем же ключом, что и установленный лаунчер."""
    from backend.core import self_update
    from backend.core.errors import NexoraError

    if args.public_key:
        self_update.UPDATE_PUBLIC_KEY = args.public_key
    elif not self_update.is_configured():
        raise SystemExit("В shared/version.py пуст UPDATE_PUBLIC_KEY — впишите ключ "
                         "или передайте --public-key")
    manifest_path = Path(args.manifest).resolve()
    signature_path = Path(str(manifest_path) + ".sig")
    if not signature_path.is_file():
        raise SystemExit(f"Нет файла подписи {signature_path}")
    try:
        data = self_update.verify_manifest(manifest_path.read_bytes(), signature_path.read_text(encoding="utf-8"))
    except NexoraError as e:
        raise SystemExit(f"Подпись не принята: {e}") from e
    print(f"Подпись верна. Версия {data['version']}, файлы: {', '.join(k for k in ('setup', 'zip') if k in data)}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True)

    keygen = commands.add_parser("keygen", help="создать пару ключей Ed25519")
    keygen.add_argument("--out", default="release_key.pem")
    keygen.add_argument("--force", action="store_true", help="перезаписать существующий ключ")
    keygen.set_defaults(func=cmd_keygen)

    sign = commands.add_parser("sign", help="собрать и подписать latest.json")
    sign.add_argument("dist", help="папка со сборкой (dist)")
    sign.add_argument("--version", default="", help=f"версия выпуска (по умолчанию {APP_VERSION})")
    sign.add_argument("--key", default="", help="файл с закрытым ключом (иначе NEXORA_RELEASE_KEY)")
    sign.add_argument("--notes", default="", help="файл с описанием выпуска")
    sign.add_argument("--page", default="", help="адрес страницы выпуска для кнопки «Подробнее»")
    sign.set_defaults(func=cmd_sign)

    verify = commands.add_parser("verify", help="проверить подпись манифеста вшитым ключом")
    verify.add_argument("manifest", help="путь к latest.json")
    verify.add_argument("--public-key", default="", help="открытый ключ base64 (иначе — вшитый в сборку)")
    verify.set_defaults(func=cmd_verify)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
