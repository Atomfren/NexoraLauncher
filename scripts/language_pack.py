"""Языковые пакеты: шаблон для переводчика, сборка пакета и подписанный список для сайта.

Выгрузить шаблон (английские строки как образец)::

    python scripts/language_pack.py template --code uk --name "Українська" --out uk.json

Переводчик заполняет значения в ``strings`` и присылает файл обратно. Проверить и собрать::

    python scripts/language_pack.py build uk.json --out site/languages/

Собрать и подписать список для сайта (из готовых пакетов в папке)::

    python scripts/language_pack.py index site/languages/ --key release_key.pem

Получится ``languages.json`` и ``languages.json.sig`` рядом с пакетами. Выкладывать всю папку
на ``https://nexoralauncher.ru/languages/``. Подпись — тем же ключом, что и обновления:
лаунчер проверяет её перед установкой перевода.
"""

import argparse
import base64
import hashlib
import json
import re
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from sign_release import load_private_key, public_key_line  # noqa: E402

from shared.i18n import _EN, _RU, pack_keys  # noqa: E402
from shared.version import UPDATE_PUBLIC_KEY  # noqa: E402

INDEX_NAME = "languages.json"


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def cmd_template(args: argparse.Namespace) -> None:
    """Шаблон перевода: все ключи с английским текстом и русским в подсказке."""
    strings = {key: _EN.get(key, "") for key in pack_keys()}
    pack = {"code": args.code, "name": args.name or args.code, "version": "1.0", "author": args.author,
            "strings": strings}
    out = Path(args.out or f"{args.code}.json")
    out.write_text(json.dumps(pack, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"{out}: {len(strings)} строк для перевода")
    if args.with_russian:
        hint = out.with_name(out.stem + "-ru-подсказки.json")
        hint.write_text(json.dumps({k: _RU.get(k, "") for k in pack_keys()}, ensure_ascii=False, indent=2) + "\n",
                        encoding="utf-8")
        print(f"{hint}: те же ключи по-русски, в пакет не входит")


def check_pack(pack: dict) -> list[str]:
    """Проверяет пакет и возвращает список замечаний (пустой — всё в порядке)."""
    problems = []
    for field in ("code", "name", "strings"):
        if not pack.get(field):
            problems.append(f"нет поля «{field}»")
    strings = pack.get("strings") or {}
    if not isinstance(strings, dict):
        return problems + ["«strings» должен быть объектом"]

    known = set(pack_keys())
    unknown = sorted(set(strings) - known)
    if unknown:
        problems.append(f"лишние ключи ({len(unknown)}): {', '.join(unknown[:5])}…")
    # Подстановки вида {name} должны совпадать с оригиналом, иначе строка сломается при показе
    for key, value in strings.items():
        # Пустое значение — просто ещё не переведено, это не ошибка: при сборке такие строки отбрасываются
        if key not in known or not isinstance(value, str) or not value.strip():
            continue
        fields = set(re.findall(r"\{(\w+)\}", _EN.get(key, "")))
        theirs = set(re.findall(r"\{(\w+)\}", value))
        if fields != theirs:
            problems.append(f"{key}: подстановки {sorted(theirs)} вместо {sorted(fields)}")
    return problems


def cmd_build(args: argparse.Namespace) -> None:
    source = Path(args.pack)
    pack = json.loads(source.read_text(encoding="utf-8"))
    problems = check_pack(pack)
    if problems:
        print("Пакет не принят:")
        for problem in problems[:20]:
            print(f"  — {problem}")
        raise SystemExit(1)

    strings = {k: v for k, v in pack["strings"].items() if isinstance(v, str) and v.strip()}
    pack["strings"] = strings
    out_dir = Path(args.out or source.parent)
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / f"{pack['code']}.json"
    target.write_text(json.dumps(pack, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    total = len(pack_keys())
    print(f"{target}: переведено {len(strings)} из {total} ({len(strings) * 100 // total}%)")
    if len(strings) < total:
        print("Непереведённые строки лаунчер покажет по-английски")


def cmd_index(args: argparse.Namespace) -> None:
    folder = Path(args.folder)
    key = load_private_key(args.key)
    total = len(pack_keys())
    entries = []
    for path in sorted(folder.glob("*.json")):
        if path.name == INDEX_NAME:
            continue
        pack = json.loads(path.read_text(encoding="utf-8"))
        problems = check_pack(pack)
        if problems:
            print(f"{path.name}: пропущен — {problems[0]}")
            continue
        raw = path.read_bytes()
        entries.append({"code": pack["code"], "name": pack["name"], "version": str(pack.get("version", "")),
                        "author": str(pack.get("author", "")), "file": path.name, "size": len(raw),
                        "sha256": sha256(raw), "translated": len(pack["strings"]), "total": total})
        print(f"  {pack['code']}: {pack['name']}, {len(pack['strings'])} из {total}")
    if not entries:
        raise SystemExit(f"В {folder} нет пригодных языковых пакетов")

    index = {"generated": date.today().isoformat(), "languages": entries}
    raw = (json.dumps(index, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    (folder / INDEX_NAME).write_bytes(raw)
    (folder / f"{INDEX_NAME}.sig").write_text(base64.b64encode(key.sign(raw)).decode("ascii") + "\n",
                                              encoding="utf-8")
    print(f"\n{folder / INDEX_NAME}\n{folder / INDEX_NAME}.sig")
    expected = public_key_line(key.public_key())
    if expected.split('"')[1] != UPDATE_PUBLIC_KEY:
        print("\nВНИМАНИЕ: открытый ключ в shared/version.py не от этого ключа — лаунчеры"
              " отвергнут этот список. Нужная строка:\n")
        print(expected)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True)

    template = commands.add_parser("template", help="шаблон перевода со всеми ключами")
    template.add_argument("--code", required=True, help="код языка, например uk или pt-br")
    template.add_argument("--name", default="", help="название языка на нём самом")
    template.add_argument("--author", default="", help="кто переводит")
    template.add_argument("--out", default="", help="куда сохранить")
    template.add_argument("--with-russian", action="store_true", help="ещё и русский текст для сверки")
    template.set_defaults(func=cmd_template)

    build = commands.add_parser("build", help="проверить и собрать пакет")
    build.add_argument("pack", help="заполненный файл перевода")
    build.add_argument("--out", default="", help="папка для готового пакета")
    build.set_defaults(func=cmd_build)

    index = commands.add_parser("index", help="собрать и подписать список для сайта")
    index.add_argument("folder", help="папка с пакетами")
    index.add_argument("--key", default="", help="закрытый ключ (иначе NEXORA_RELEASE_KEY)")
    index.set_defaults(func=cmd_index)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
