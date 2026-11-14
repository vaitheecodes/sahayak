# Dev state (2026-11-13)

Branch `main`, last code commit `d1162ac`; 38 commits ahead of `origin/main`
(this file included), none pushed. Full suites green on `d1162ac`:
SQLite 1450 passed / 3 skipped, Postgres 1437 passed / 16 skipped (the
gaps are the SQLite-only and Postgres-only tests).

## Built (this round)
- Chat contract, 16 rules: `docs/CHAT_CONTRACT.md`.
- Real-model chat eval: `backend/evals/` (simulator, code rules, Nova Pro
  judge, call cap and ledger, original-rules rescoring, feedback replays).
- Chat fixes found by the eval:
  - greeting, acknowledgments, one clarifying question;
  - language tags from the latest message only;
  - instructions must be backed by the KB entry;
  - query rewrite on a weak KB match; how-to task check;
  - follow-up coverage check, then a ticket offer;
  - "what are the sources?" answered by code; prompt-echo guard;
  - outage replies (chat: ticket offer; ticket: "A person will reply here soon");
  - EU snippet sentence and default-domain line.
- Feedback button "This reply was wrong" (`chat_feedback`, Postgres 0009).
- Idle timeout for open chats; tickets close only when the customer says it is solved.
- Audit fixes: password change revokes tokens, per-attempt KB call budget,
  upload lock, admin attachment 403, midnight runs, login timing.

## Latest eval (adcc604, before the NameError and EU-snippet fixes)
| Run | Current rules | Original rules | Hard fails, rules 1/3/9 |
|---|---|---|---|
| Lite #1 | 84/86 = 98% | 36/86 | 0 / 0 / 0 |
| Lite #2 | 82/85 = 96% | 35/85 | 0 / 0 / 0 |
| Pro | 82/86 = 95% | 34/86 | 0 / 0 / 0 |

Affected cases on `d1162ac`: 7 of 8 pass (the seeds and the CSP entry).
Seed (b) fails only the judge's helpfulness on a correct ticket.

## Ledger
15,068 Bedrock calls of the approved 16,000; $4.66 in total
(`.local/chat-eval/ledger.json`). Pilot chat model: Nova Lite.

## Latest fixes (after the eval: invented URL, rewrite outage, Hinglish coverage)
- URLs/domains in a reply must be in the answering entry or the customer's
  messages (the clarify path used to allow any of 3 candidates).
- A failed rewrite call is an AI failure (outage reply + audit), not "no guide".
- `covers_latest` gets the previous customer message and the top two guides.
- Known limit: live probe, 4 attempts each: pair 1 agrees (covered, both
  languages); pair 2 differs (English "not covered" 4/4, Hinglish covered 4/4).
- Suites on the final code: SQLite 1490 passed / 3 skipped, Postgres 1477 / 16.

## Open items
- No full eval run on `d1162ac` yet. The NameError and EU-snippet fixes were
  checked only by unit tests and the affected cases.
- Claim check: planned, not built. The runs showed no invented steps.
- Rule 11 ("sources" and similar follow-ups) is 67-83%.
- The judge marks correct "no guide" tickets as unhelpful (rule 16 noise).
- The mobile app still shows its own outage banner; it hasn't been updated.
- "How do I raise a ticket?" no longer raises one; check the wording with real users.
- `.env.example` has local changes (your data): never stage it.

## Run
- Demo: `scripts/webdemo.sh start` (backend :8010, frontend :5180; uses `.env`).
- Suites: `.venv/bin/python -m pytest -q`; Postgres:
  `eval "$(PG_LOCAL_PORT=5434 scripts/pg_local.sh env)"` first.
- Eval: `scripts/chat_eval.sh --estimate`, then
  `scripts/chat_eval.sh --bot-model lite --budget 16000`.
  Seeds: `--kb demo --extra-cases .local/chat-eval/cases/seeds-demo.json --cases seed-a-hi-then-csp ...`.
  Rescore both ways: `.venv/bin/python -m backend.evals.rescore RUN`.
