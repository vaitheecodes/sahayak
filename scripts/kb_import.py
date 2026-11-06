"""Load a KB pack into the database as approved entries, or export one.

    .venv/bin/python scripts/kb_import.py PACK.json      # import (asks first)
    .venv/bin/python scripts/kb_import.py --export OUT.json

A pack (format: backend/kb_store.py, example: tests/fixtures/kb/
brightdesk.json) carries reviewed entries and confirmed terms between
environments, e.g. from staging to production. Everything in it is
imported as approved and confirmed, so only import a pack that was
reviewed; drafts from sources go through the ingester and the review
screen instead. Nothing is written if any entry is invalid. Uses the
database the app would use (DB_BACKEND, DB_PATH / DATABASE_URL).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend import categories, db, kb_store  # noqa: E402  (also loads .env via backend/__init__)

ACTOR = "script:kb_import"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("pack", nargs="?", help="pack JSON to import")
    parser.add_argument("--export", metavar="OUT", help="write the approved KB to OUT instead")
    parser.add_argument("--yes", action="store_true", help="don't ask before importing")
    args = parser.parse_args()
    if bool(args.pack) == bool(args.export):
        parser.error("give a pack to import, or --export OUT")
    db.init_db()
    conn = db.get_connection()
    try:
        categories.load(conn)
        if args.export:
            pack = kb_store.export_pack(conn)
            Path(args.export).write_text(json.dumps(pack, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
            print(f"exported {len(pack['entries'])} entries and {len(pack['terms'])} terms")
            return 0
        pack = json.loads(Path(args.pack).read_text(encoding="utf-8"))
        entries = pack.get("entries") if isinstance(pack, dict) else None
        print(f"{args.pack}: {len(entries or [])} entries, {len(pack.get('terms') or [])} terms, "
              "all to be imported as approved")
        if not args.yes and input('Type "yes" to import: ').strip().lower() != "yes":
            print("nothing imported")
            return 1
        try:
            counts = kb_store.import_pack(conn, pack, ACTOR)
        except ValueError as exc:
            conn.rollback()
            print(f"nothing imported: {exc}", file=sys.stderr)
            return 1
        conn.commit()
        print(f"imported {counts['entries']} entries and {counts['terms']} terms")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
