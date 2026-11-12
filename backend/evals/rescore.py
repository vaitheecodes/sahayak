"""Score saved runs two ways, side by side, with no model calls:
the current rules (as stored in the run) and the original rules the
baseline was scored with (rules_original.py + the original judge-derived
rules: rule 16 needs helpfulness on off-topic too). The judge's own
verdicts are reused as stored (the rubric is the run's).

    .venv/bin/python -m backend.evals.rescore RUN [RUN ...]
"""

from __future__ import annotations

import json
import sys

from backend.evals import harness, rules_original
from backend.evals.run import RULES, _passed


def original_verdicts(row: dict, pack: dict, kb: str) -> dict:
    result, v = row["result"], row["judge"]
    out = rules_original.check(result, pack, kb)
    # Rule 1's judge part: the stored verdict already holds the re-judged dispute.
    if out[1][0] == "pass" and row["verdicts"]["1"][0] == "disputed":
        out[1] = tuple(row["verdicts"]["1"])
    if out[3][0] == "fail" and not v["covered"]:
        out[3] = ("disputed", out[3][1])
    if result["case"]["expected"] == "not_covered" and v["covered"]:
        out[9] = ("n/a", "")
    if result["case"]["kind"] == "out_of_scope" and out[12][0] == "pass" and v["tone"] < 4:
        out[12] = ("fail", f"tone {v['tone']}")
    out[16] = ("pass", "") if v["helpful"] >= 3 and v["tone"] >= 4 else ("fail", "")
    return out


def score(run: str) -> dict:
    rows = [r for r in json.loads((harness.OUT / "runs" / run / "results.json").read_text())
            if not r["result"].get("error") and r["judge"]]
    packs = {kb: harness.load_pack(kb)[0] for kb in {r["result"]["case"]["kb"] for r in rows}}
    current = [{int(k): v for k, v in r["verdicts"].items()} for r in rows]
    original = [original_verdicts(r, packs[r["result"]["case"]["kb"]], r["result"]["case"]["kb"]) for r in rows]
    return {"n": len(rows), "current": current, "original": original}


def _rate(verdicts: list[dict], rule: int) -> str:
    counted = [v[rule][0] for v in verdicts if v[rule][0] != "n/a"]
    return f"{100 * counted.count('pass') / len(counted):.0f}%" if counted else "-"


def main(runs: list[str]) -> None:
    scored = {run: score(run) for run in runs}
    head = " | ".join(f"{run} current | original" for run in runs)
    print(f"| # | Rule | {head} |\n|---|---|" + "---|---|" * len(runs))
    for n, name in RULES.items():
        cells = " | ".join(f"{_rate(s['current'], n)} | {_rate(s['original'], n)}" for s in scored.values())
        print(f"| {n} | {name} | {cells} |")
    cells = " | ".join(
        f"{sum(map(_passed, s['current']))}/{s['n']} | {sum(map(_passed, s['original']))}/{s['n']}"
        for s in scored.values())
    print(f"| | **Overall** | {cells} |")


if __name__ == "__main__":
    main(sys.argv[1:])
