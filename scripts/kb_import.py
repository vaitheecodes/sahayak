"""Load a KB pack into the database as approved entries, or export one.

    .venv/bin/python scripts/kb_import.py PACK.json      # import (asks first)
    .venv/bin/python scripts/kb_import.py --dry-run PACK.json
    .venv/bin/python scripts/kb_import.py --export OUT.json
    python3 scripts/kb_import.py --count PACK.json       # counts only, no database

A pack (format: backend/kb_store.py, example: tests/fixtures/kb/
brightdesk.json) carries reviewed entries and confirmed terms between
environments, e.g. from staging to production. Everything in it is
imported as approved and confirmed, so only import a pack that was
reviewed; drafts from sources go through the ingester and the review
screen instead. Nothing is written if any entry is invalid. Uses the
database the app would use (DB_BACKEND, DB_PATH / DATABASE_URL).

A pack is data: it is parsed as JSON and checked by kb_store's
validation, never executed. PACK may be s3://bucket/key (the pilot's
one-off import task, scripts/aws_kb_import.sh). --dry-run validates it
against the database and rolls back. --counts-only prints nothing but
`KB_IMPORT <event> name=number` lines (no titles, ids or validation
messages), so its output can go to a log and be shown safely.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

ACTOR = "script:kb_import"
MAX_PACK_BYTES = 20 * 1024 * 1024


class Unreadable(Exception):
    """The pack isn't there, is too big, or isn't JSON."""


def read_pack(source: str):
    if source.startswith("s3://"):
        import boto3  # only in the image / the venv

        bucket, _, key = source[len("s3://"):].partition("/")
        if not bucket or not key:
            raise Unreadable
        try:
            body = boto3.client("s3").get_object(Bucket=bucket, Key=key)["Body"].read(MAX_PACK_BYTES + 1)
        except Exception as exc:  # noqa: BLE001 - any S3 failure: unreadable, no details printed
            raise Unreadable from exc
    else:
        path = Path(source)
        if not path.is_file() or path.stat().st_size > MAX_PACK_BYTES:
            raise Unreadable
        body = path.read_bytes()
    if len(body) > MAX_PACK_BYTES:
        raise Unreadable
    try:
        return json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise Unreadable from exc


def pack_counts(pack) -> dict[str, int]:
    """Entries, terms, distinct categories and distinct licences; zeros
    for anything that isn't the expected shape (validation says why)."""
    entries = pack.get("entries") if isinstance(pack, dict) else None
    entries = [e for e in entries if isinstance(e, dict)] if isinstance(entries, list) else []
    terms = pack.get("terms") if isinstance(pack, dict) else None
    return {
        "entries": len(entries),
        "terms": len(terms) if isinstance(terms, list) else 0,
        "categories": len({e.get("category") for e in entries if isinstance(e.get("category"), str)}),
        "licences": len({e["source_licence"] for e in entries
                         if isinstance(e.get("source_licence"), str) and e["source_licence"].strip()}),
    }


def line(event: str, **counts: int) -> str:
    return " ".join(["KB_IMPORT", event, *(f"{k}={int(v)}" for k, v in counts.items())])


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("pack", nargs="?", help="pack JSON to import (a path or s3://bucket/key)")
    parser.add_argument("--export", metavar="OUT", help="write the approved KB to OUT instead")
    parser.add_argument("--count", action="store_true", help="print the pack's counts only; no database")
    parser.add_argument("--dry-run", action="store_true", help="validate against the database, write nothing")
    parser.add_argument("--counts-only", action="store_true", help="print only KB_IMPORT count lines")
    parser.add_argument("--yes", action="store_true", help="don't ask before importing")
    args = parser.parse_args()
    if bool(args.pack) == bool(args.export):
        parser.error("give a pack to import, or --export OUT")
    quiet = args.counts_only or args.count

    if args.pack:
        try:
            pack = read_pack(args.pack)
        except Unreadable:
            print(line("unreadable") if quiet else f"{args.pack}: not a readable pack (missing, too big, or not JSON)")
            return 1
        counts = pack_counts(pack)
        if quiet:
            print(line("pack", **counts))
        if args.count:
            return 0

    from backend import categories, db, kb_store  # also loads .env via backend/__init__

    db.init_db()
    conn = db.get_connection()
    try:
        categories.load(conn)
        if args.export:
            pack = kb_store.export_pack(conn)
            Path(args.export).write_text(json.dumps(pack, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
            print(f"exported {len(pack['entries'])} entries and {len(pack['terms'])} terms")
            return 0
        if not quiet:
            print(f"{args.pack}: {counts['entries']} entries, {counts['terms']} terms, "
                  f"{counts['categories']} categories, {counts['licences']} licences"
                  + (" (dry run: nothing is written)" if args.dry_run else ", all to be imported as approved"))
        if not args.dry_run and not args.yes and input('Type "yes" to import: ').strip().lower() != "yes":
            print("nothing imported")
            return 1
        try:
            result = kb_store.import_pack(conn, pack, ACTOR)
        except ValueError as exc:
            conn.rollback()
            if quiet:
                print(line("invalid"))
            else:
                print(f"nothing imported: {exc}", file=sys.stderr)
            return 1
        if args.dry_run:
            conn.rollback()
            print(line("dry_run_ok", entries=result["entries"], terms=result["terms"]) if quiet
                  else f"dry run: {result['entries']} entries and {result['terms']} terms would be imported")
            return 0
        conn.commit()
        print(line("imported", entries=result["entries"], terms=result["terms"]) if quiet
              else f"imported {result['entries']} entries and {result['terms']} terms")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
