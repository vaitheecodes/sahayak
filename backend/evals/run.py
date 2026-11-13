"""scripts/chat_eval.sh [--kb demo brightdesk] [--bot-model lite|pro] [--max-calls 3500]
[--rerun-failed RUN] [--estimate] [--allow-over]

Prints the estimated Bedrock calls first and stops (exit 2) when the
estimate is above --max-calls or the ledger's total budget, unless
--allow-over. The cap is hard: past it every call is refused."""

from __future__ import annotations

import argparse
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from backend.evals import harness

RULES = {1: "never invent", 2: "small talk", 3: "KB-covered is answered", 4: "how-to: no troubleshooting",
         5: "one specific clarifying question", 6: "no repeated question", 7: "ok/thanks don't close",
         8: "no repeated sentences", 9: "not covered: no guide + ticket", 10: "snippet matches text",
         11: "follow-ups work", 12: "off-topic: polite, brief", 13: "human: ticket at once",
         14: "always answers", 15: "no internal text", 16: "helpful and kind (judge)"}
STRICT = (1, 3)
BOT_CALLS_PER_TURN = 3   # continuation/classify + answer, sometimes a regenerated reply or a summary


def estimate(cases_by_kb: dict) -> int:
    """Upper-ish: every case runs all its turns; the judge once (+30% judged twice)."""
    return int(sum(c.turns * (BOT_CALLS_PER_TURN + (1 if c.simulate else 0)) + 1.3
                   for cases in cases_by_kb.values() for c in cases))


def _verdicts(result, pack, kb, verdict_fn):
    from backend.evals import rules

    out = rules.check(result, pack, kb)
    if result.get("error"):
        return out, None
    v = verdict_fn(result, pack)
    if v.invented and out[1][0] == "pass":
        again = verdict_fn(result, pack)
        out[1] = ("disputed", "; ".join(v.invented)) if again.invented else out[1]
    if out[3][0] == "fail" and not v.covered:
        out[3] = ("disputed", out[3][1] + " (judge: the KB doesn't cover it)")
    if result["case"]["expected"] == "not_covered" and v.covered:
        out[9] = ("n/a", "judge: covered after all")
    tone_ok = v.tone >= 4
    if result["case"]["kind"] == "out_of_scope" and out[12][0] == "pass" and not tone_ok:
        out[12] = ("fail", f"tone {v.tone}")
    # Off-topic: declining is right, so only the tone counts.
    helpful_ok = v.helpful >= 3 or result["case"]["kind"] == "out_of_scope"
    out[16] = ("pass", "") if helpful_ok and tone_ok else ("fail", f"helpful {v.helpful}, tone {v.tone}: {v.note}")
    return out, v.model_dump()


def _passed(verdicts: dict) -> bool:
    return all(v[0] in ("pass", "n/a") for v in verdicts.values())


def report(run_dir: Path, rows: list[dict], packs: dict, calls: dict, bot_model: str) -> str:
    done = [r for r in rows if not r["result"].get("error")]
    lines = [f"# Chat eval {run_dir.name}", "", f"Bot answer model: {bot_model}. Conversations: {len(done)}"
             f" ({len(rows) - len(done)} left out: {sum(r['result'].get('error') == 'infra_error' for r in rows)} provider "
             f"outage (infra_error), the rest call cap or simulator/judge failure). Calls: {calls['total_calls']}"
             f" {calls['calls']}, cost ${calls['cost_usd']:.2f}.", "",
             "| # | Rule | Pass | Fail | Disputed | Pass rate |", "|---|---|---|---|---|---|"]
    for n, name in RULES.items():
        counts = {k: sum(1 for r in done if r["verdicts"][n][0] == k) for k in ("pass", "fail", "disputed")}
        total = sum(counts.values())
        rate = f"{100 * counts['pass'] / total:.0f}%" if total else "-"
        lines.append(f"| {n} | {name} | {counts['pass']} | {counts['fail']} | {counts['disputed']} | {rate} |")
    overall = sum(1 for r in done if _passed(r["verdicts"]))
    lines += ["", f"**Overall: {overall}/{len(done)} = {100 * overall / max(len(done), 1):.0f}%**", ""]
    for kb in packs:
        kb_rows = [r for r in done if r["result"]["case"]["kb"] == kb]
        ok = sum(1 for r in kb_rows if _passed(r["verdicts"]))
        lines.append(f"- {kb}: {ok}/{len(kb_rows)}")
    worst = sorted((r for r in done if not _passed(r["verdicts"])),
                   key=lambda r: (-sum(v[0] != "pass" and v[0] != "n/a" for v in r["verdicts"].values()),
                                  (r["judge"] or {}).get("helpful", 5)))[:10]
    lines += ["", "## Worst 10", ""]
    for r in worst:
        lines += _transcript(r)
    disputed = [r for r in done if any(r["verdicts"][n][0] == "disputed" for n in STRICT)]
    lines += ["", "## Disputed (rules 1 and 3): for review", ""]
    for r in disputed:
        case = r["result"]["case"]
        entry = next((e for e in packs[case["kb"]]["entries"] if e["kb_entry_id"] == case.get("entry_id")), None)
        from backend.evals.cases import _entry_text
        convo = "<br>".join(f"**Customer:** {_cell(t['customer'])}<br>**Bot:** {_cell(t['bot'])}"
                            for t in r["result"]["turns"])
        lines += [f"### {case['case_id']}", "",
                  *[f"- Rule {n}: {r['verdicts'][n][1]}" for n in STRICT if r["verdicts"][n][0] == "disputed"], "",
                  "| Conversation | KB entry |", "|---|---|",
                  f"| {convo} | {_cell(_entry_text(entry)) if entry else 'none (not in the KB)'} |", ""]
    if not disputed:
        lines.append("None.")
    return "\n".join(lines)


def _cell(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", "<br>")


def _transcript(r: dict) -> list[str]:
    case = r["result"]["case"]
    failed = [f"rule {n} ({RULES[n]}): {d}" for n, (v, d) in r["verdicts"].items() if v in ("fail", "disputed")]
    out = [f"### {case['case_id']} ({case['kind']}, expected {case['expected']})", "", *[f"- {f}" for f in failed], ""]
    for t in r["result"]["turns"]:
        out += [f"> **Customer:** {t['customer']}", ">", *[f"> {line}" for line in t["bot"].splitlines()],
                f"> *({t['status']}{', ' + t['ticket_id'] if t['ticket_id'] else ''})*", ""]
    return out


def _run_cases(cases_by_kb, packs, rows, workers, counted, run_dir):
    from backend.ai_service import AIError
    from backend.evals import judge, simulate

    for kb, kb_cases in cases_by_kb.items():
        pack, product = packs[kb]
        client = harness.open_app(run_dir / f"{kb}.db", pack, product)
        try:
            with ThreadPoolExecutor(workers) as pool:
                results = list(pool.map(lambda c: simulate.run(client, c), kb_cases))
            for result in results:   # provider outages: left out of the score, counted apart
                if not result.get("error") and any(t["ai_error"] for t in result["turns"]) \
                        and harness.infra_error(result.get("session_id")):
                    result["error"] = "infra_error"

            def score(result):
                try:
                    return _verdicts(result, pack, kb, judge.judge)
                except (harness.CapReached, AIError) as exc:   # not the bot's fault: left out
                    result["error"] = f"judge: {exc}"
                    return {}, None
            with ThreadPoolExecutor(workers) as pool:
                scored = list(pool.map(score, results))
        finally:
            client.__exit__(None, None, None)
        for result, (verdicts, v) in zip(results, scored):
            rows.append({"result": result, "verdicts": verdicts, "judge": v})
        print(f"{kb}: {len(results)} conversations, {counted.total} calls so far")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kb", nargs="+", default=["demo", "brightdesk"], choices=["demo", "brightdesk"])
    parser.add_argument("--bot-model", default="lite", choices=["lite", "pro"])
    parser.add_argument("--max-calls", type=int, default=3500)
    parser.add_argument("--budget", type=int, default=19000, help="total calls across runs (the ledger)")
    parser.add_argument("--rerun-failed", metavar="RUN", help="only the cases that failed in that run")
    parser.add_argument("--cases", nargs="+", metavar="CASE_ID", help="only these cases")
    parser.add_argument("--estimate", action="store_true")
    parser.add_argument("--allow-over", action="store_true")
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--extra-cases", metavar="FILE", help="more cases (a JSON list), e.g. kept in .local/")
    args = parser.parse_args(argv)

    bot_model = harness.NOVA_PRO if args.bot_model == "pro" else harness.NOVA_LITE
    harness.prepare_env(bot_model)
    from backend.evals import cases as cases_mod

    counted = harness.install_counted_backend(args.max_calls)
    packs = {kb: harness.load_pack(kb) for kb in args.kb}
    spent = harness.ledger()["spent"]
    # Generating cases is one call per entry, once (cached): done even for --estimate.
    cases_by_kb = {kb: cases_mod.load_or_generate(kb, p) for kb, (p, _) in packs.items()}
    if counted.total:
        harness.record("generate-cases", counted.summary())
        print(f"Generated cases: {counted.total} calls.")
        spent = harness.ledger()["spent"]
        for counter in (counted.calls, counted.tokens_in, counted.tokens_out):
            counter.clear()
    if "demo" in cases_by_kb:
        cases_by_kb["demo"] += cases_mod.feedback_cases()
    if args.extra_cases:
        for extra in json.loads(Path(args.extra_cases).read_text()):
            case = cases_mod.Case(**extra)
            if case.kb in cases_by_kb:
                cases_by_kb[case.kb].append(case)
    cases_by_kb = {kb: cases_mod.variants(cs) for kb, cs in cases_by_kb.items()}
    keep = set(args.cases or [])
    if args.rerun_failed:
        prev = json.loads((harness.OUT / "runs" / args.rerun_failed / "results.json").read_text())
        keep |= {r["result"]["case"]["case_id"] for r in prev if not _passed({int(k): v for k, v in r["verdicts"].items()})}
    if keep:
        cases_by_kb = {kb: [c for c in cs if c.case_id in keep] for kb, cs in cases_by_kb.items()}
    planned = estimate(cases_by_kb)
    n_cases = sum(len(c) for c in cases_by_kb.values())
    past = [r for r in harness.ledger()["runs"] if r["run"].endswith(f"-{args.bot_model}") and r["total_calls"]]
    per_call = sum(r["cost_usd"] for r in past) / max(sum(r["total_calls"] for r in past), 1)
    print(f"Estimate: about {planned} Bedrock calls for {n_cases} conversations, about ${planned * per_call:.2f} "
          f"(cap {args.max_calls}; spent so far {spent} of the {args.budget} budget).")
    if args.estimate:
        return 0
    if (planned > args.max_calls or spent + planned > args.budget) and not args.allow_over:
        print("Above the cap or the budget: not started. Raise --max-calls/--budget or pass --allow-over.")
        return 2

    run_id = time.strftime("%Y%m%d-%H%M%S") + f"-{args.bot_model}"
    run_dir = harness.OUT / "runs" / run_id
    run_dir.mkdir(parents=True)
    rows = []
    try:
        _run_cases(cases_by_kb, packs, rows, args.workers, counted, run_dir)
    finally:
        totals = harness.record(run_id, counted.summary())   # spent calls count even after a crash
    calls = counted.summary()

    rows = [r for r in rows if r["verdicts"]] + [r for r in rows if not r["verdicts"]]
    for r in rows:
        r["verdicts"] = r["verdicts"] or {n: ("n/a", "") for n in RULES}
    (run_dir / "results.json").write_text(json.dumps(rows, indent=1, ensure_ascii=False))
    failures = run_dir / "failures"
    failures.mkdir()
    for r in rows:
        if not _passed(r["verdicts"]) and not r["result"].get("error"):
            (failures / f"{r['result']['case']['case_id']}.json").write_text(json.dumps(r, indent=1, ensure_ascii=False))
    text = report(run_dir, rows, {kb: p for kb, (p, _) in packs.items()}, calls, bot_model)
    (run_dir / "report.md").write_text(text)
    print(text.split("## Worst 10")[0])
    print(f"Run {run_id}: {run_dir / 'report.md'}. Ledger: {totals['spent']} calls, ${totals['cost_usd']:.2f}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
