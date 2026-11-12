"""Chat evaluation against the real model (docs/CHAT_CONTRACT.md).

A model plays customers against the real chat pipeline (/api/chats, in
process, on a fresh SQLite database holding one KB); code rules and a
judge model check every conversation against the contract.

- harness.py   eval database with a KB, counted Bedrock client (hard cap,
               tokens, cost), the call ledger across runs
- cases.py     test conversations per KB entry and per KB, generated once
               and cached; feedback-button transcripts as replay cases
- simulate.py  runs one case: the simulated customer reacts to each reply
- rules.py     the contract's code rules
- judge.py     the judge model: invented steps/claims, coverage, help, tone
- run.py       CLI (scripts/chat_eval.sh): estimate, cap, run, report

Not shipped in the image (.dockerignore). Outputs in .local/chat-eval/.
"""
