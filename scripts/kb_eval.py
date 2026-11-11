"""Evaluate KB drafting on the saved fixture pages (tests/fixtures/kb/pages).

Each page is cleaned, chunked and drafted exactly as an ingest run would
(kb_ingester.drafting.draft_chunk, all checks), with no database. Reported
per page and in total:

  instruction recall  share of the page's instructions (expected.json)
                      covered by a kept step's quote or a kept snippet
  steps               proposed by the model / kept after the checks
  invented            steps with no quote, or that the second check said
                      their quote doesn't support
  quote failures      quotes that aren't a passage of the section, or too long
  incomplete          entries flagged as missing steps of an ordered list
  model calls, tokens and cost (Bedrock usage; Nova Lite / Pro list prices)

It makes real model calls with the configured provider (AI_PROVIDER, e.g.
bedrock with AWS_PROFILE): a few hundredths of a cent per page with Nova
Lite. Nothing is stored; --out writes the drafts and metrics as JSON.

    AI_PROVIDER=bedrock AWS_PROFILE=ticketapp .venv/bin/python scripts/kb_eval.py --out eval.json
    ... scripts/kb_eval.py --drafting-model apac.amazon.nova-pro-v1:0   (drafting only)
    ... scripts/kb_eval.py --pages .local/kb-eval   (pages kept out of git, with their own expected.json)
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.ai_service import backends, provider  # noqa: E402
from kb_ingester import checks, chunking, clean  # noqa: E402
from kb_ingester.drafting import Budget, draft_chunk  # noqa: E402

PAGES = ROOT / "tests" / "fixtures" / "kb" / "pages"
# USD per 1M tokens (input, output), Bedrock Mumbai list price.
PRICES = {"nova-lite": (0.071, 0.284), "nova-pro": (0.94, 3.76)}
INVENTED = ("quote_missing", "not_supported")
QUOTE_FAILURES = ("quote_not_in_source", "quote_length")
STEP_DROPS = INVENTED + QUOTE_FAILURES


def _price(model_id: str) -> tuple[float, float]:
    return next((p for key, p in PRICES.items() if key in model_id), PRICES["nova-lite"])


def evaluate(name: str, spec: dict, usage: list, pages: Path = PAGES) -> dict:
    page = clean.html_to_text((pages / f"{name}.html").read_bytes())
    chunks, _ = chunking.chunk_text(page.text)
    drafts, dropped, calls, incomplete = [], Counter(), 0, 0
    start = len(usage)
    for chunk in chunks:
        budget = Budget(100)
        try:
            result = draft_chunk(chunk.text, heading_path=chunk.heading_path, page_title=page.title,
                                 source_url=spec["url"], known_terms=[], budget=budget)
        except provider.AIError as exc:
            dropped["ai_error"] += 1
            calls += budget.used
            print(f"  {chunk.heading_path}: AI error ({exc.failure.code if exc.failure else exc})")
            continue
        calls += result.calls
        dropped.update(result.dropped)
        for entry in result.entries:
            expected = entry.get("notes", {}).get("procedure_steps")
            if expected and len(entry["steps"]) < expected:
                incomplete += 1
            drafts.append({**entry, "section": chunk.heading_path})
    quotes = [checks.normalize(s["quote"]) for d in drafts for s in d["steps"]]
    quotes += [checks.normalize(s) for d in drafts for s in d.get("snippets", [])]
    covered = [k for k in spec["instructions"] if any(k in q for q in quotes)]
    kept = sum(len(d["steps"]) for d in drafts)
    tokens_in = sum(u.get("inputTokens", 0) for u in usage[start:])
    tokens_out = sum(u.get("outputTokens", 0) for u in usage[start:])
    with backends.model_task("draft_kb_entries"):
        price = _price(backends.BedrockBackend.model_id())
    return {
        "page": name, "sections": len(chunks), "drafts": len(drafts), "model_calls": calls,
        "instructions": len(spec["instructions"]), "covered": len(covered),
        "missed": [k for k in spec["instructions"] if k not in covered],
        "steps_proposed": kept + sum(dropped[c] for c in STEP_DROPS), "steps_kept": kept,
        "invented": sum(dropped[c] for c in INVENTED), "quote_failures": sum(dropped[c] for c in QUOTE_FAILURES),
        "incomplete": incomplete, "dropped": dict(dropped), "tokens_in": tokens_in, "tokens_out": tokens_out,
        "cost_usd": round(tokens_in / 1e6 * price[0] + tokens_out / 1e6 * price[1], 5), "entries": drafts,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", help="write drafts and metrics as JSON")
    parser.add_argument("--page", action="append", help="only these fixture pages")
    parser.add_argument("--pages", type=Path, default=PAGES,
                        help="a folder of pages and their expected.json (default: the fixture pages)")
    parser.add_argument("--drafting-model", help="Bedrock model ID for drafting only (as the ai_models setting)")
    args = parser.parse_args()
    if args.drafting_model:
        from backend import app_settings

        app_settings._overrides["ai_models"] = {"draft_kb_entries": args.drafting_model}
    spec = json.loads((args.pages / "expected.json").read_text())["pages"]
    usage: list = []
    if provider.provider_name() == "bedrock":
        provider.set_backend(backends.BedrockBackend(on_usage=usage.append))
    with backends.model_task("draft_kb_entries"):
        drafting_model = backends.BedrockBackend.model_id()
    print(f"provider={provider.provider_name()} drafting model={drafting_model} "
          f"(cost uses its price for every call)")
    results = [evaluate(name, spec[name], usage, args.pages) for name in spec if not args.page or name in args.page]
    header = f"{'page':24} {'recall':>8} {'kept/prop':>10} {'invented':>8} {'quote fail':>10} {'incompl':>7} " \
             f"{'drafts':>6} {'calls':>5} {'cost $':>8}"
    print(header)
    for r in results:
        print(f"{r['page']:24} {r['covered']:>3}/{r['instructions']:<4} {r['steps_kept']:>4}/{r['steps_proposed']:<5} "
              f"{r['invented']:>8} {r['quote_failures']:>10} {r['incomplete']:>7} {r['drafts']:>6} "
              f"{r['model_calls']:>5} {r['cost_usd']:>8.4f}")
        if r["missed"]:
            print(f"{'':24} missed: {'; '.join(r['missed'])}")
    total = {k: sum(r[k] for r in results) for k in ("covered", "instructions", "steps_kept", "steps_proposed",
                                                      "invented", "quote_failures", "incomplete", "drafts",
                                                      "model_calls", "cost_usd")}
    print(f"{'TOTAL':24} {total['covered']:>3}/{total['instructions']:<4} {total['steps_kept']:>4}/"
          f"{total['steps_proposed']:<5} {total['invented']:>8} {total['quote_failures']:>10} "
          f"{total['incomplete']:>7} {total['drafts']:>6} {total['model_calls']:>5} {total['cost_usd']:>8.4f}")
    if args.out:
        Path(args.out).write_text(json.dumps({"total": total, "pages": results}, indent=1, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
