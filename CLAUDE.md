# Sahayak

An AI help desk for any product: ticketing, AI chat, a support engineer
workspace, incident correlation and an admin console, plus a generic KB
ingester (`kb_ingester/`) and a mobile app (`mobile/`,
untracked, not part of this work). Started as a copy of ticketapp-ai-aws
@ b77e159; never edit `../ticketapp-ai-aws`.

## Project goal

The first client's product (a third-party HRMS) is unknown to us, so the
core is product-neutral: the product's name, categories, terms and
knowledge base are data, never code.

1. **Neutral core (done, Stage 1)** — no product data, wording or
   vocabulary in code or prompts; Sahayak starts with an EMPTY KB.
   - Product profile: app_settings section `product` (name, one-line
     description, support team name; `backend/product.py`). Prompts say
     `product.described()` ("Brightdesk HR (an HR management system)"),
     or "the product" while unnamed. Admin: Settings → Product.
   - Categories: rows in `kb_categories` (`backend/categories.py`),
     seeded once with ACCOUNT, BILLING, DATA, SETUP, USAGE, ISSUE,
     INTEGRATION, OTHER; only `confirmed` ones are used; cached per
     process (`load()` at startup). The classifier's schema is narrowed to
     them at call time (`schemas.with_categories`). Default high-risk:
     whichever of ACCOUNT / BILLING / DATA exist. Default departments:
     Product Support, Accounts & Billing, General.
   - KB in the database (`backend/kb_store.py`): see "Knowledge base"
     below. No order lookup (the e-commerce `orders` mock is gone;
     `0003_kb.sql` drops it).
   - Test fixture: `tests/fixtures/kb/brightdesk.json`, a fictional HR
     product (10 entries, 7 terms). `tests/kb_fixture.load()` puts it in
     memory (call it after a TestClient has started: startup reloads
     settings); conftest gives every test an empty KB and no terms.
     `tests/test_product_neutral.py` fails if product words (Site24x7,
     monitor, APM, ...) reappear in code, prompts, migrations or frontend.
2. **Generic KB ingester** — `kb_ingester/`, mounted by the backend at
   `/api/kb` and shipped with it (Dockerfile, AppSail, deploy workflow).
   Sources: one web page, an uploaded TXT/MD/PDF, pasted text. See "KB
   ingester" below. Still to come: site crawl (robots.txt is already
   honoured per page), sitemaps, forum threads, resolved tickets.

## KB ingester (`kb_ingester/`)

One URL -> SafeFetcher -> clean -> chunk -> draft -> checks -> drafts ->
review. Module map in `kb_ingester/__init__.py`.

- **SafeFetcher** (`safe_fetch.py`): http/https on 80/443 only, no
  userinfo, no localhost/.internal/.local names; every resolved address
  must be public (private, loopback, link-local, CGNAT, multicast,
  reserved, docs, ULA, IPv4-mapped/6to4/NAT64 checked inside, metadata
  169.254.169.254 / fd00:ec2::254 named); connects to the checked IP (TLS
  verified for the host name), so DNS rebinding can't swap it; redirects
  by hand, max 5, each re-checked; 5 MB cap (declared, streamed, and after
  gzip), 10 s socket timeout + 30 s deadline, content-type allowlist,
  `Accept-Encoding: identity`, 1 request/s per host. Errors are reason
  codes. `UrlSource` (`sources.py`) checks robots.txt (4xx: allowed;
  5xx: disallowed) for `SahayakKBBot`. Tests fake DNS and servers
  (`tests/kb_ingest_helpers.FakeWeb`).
- **Clean / chunk**: bs4 `html.parser` (no lxml); nav, aside, forms,
  cookie/consent/share widgets, hidden elements and heading permalinks
  go; h1-h3 become `#` lines; `<pre>` sits between ``` lines and inline
  `<code>` in backticks; each list item is ONE `N. ` / `- ` line
  (its paragraphs joined, nested lists indented two spaces), and the
  " ," a removed inline icon leaves is closed up; chunks are heading
  sections of 300-1,200 words (small ones merged, long ones split at
  blank lines), max 40 per page.
- **Files and pasted text** (`files.py`): `POST /api/kb/sources/upload`
  (multipart; .txt/.md/.pdf, 10 MB, content checked: UTF-8 text or
  `%PDF-`; request size refused early by `main._UploadSizeLimit`) and
  `/sources/text` (200k characters) create a source (kind file / text,
  same confirmation and licence note) and return its estimate; a new run
  needs a new upload/paste (`/sources/{id}/upload|text`): the content is
  never kept, only hashed (one document per source, so versions compare).
  PDF: pypdf text page by page (no OCR), headings guessed by
  `files.mark_headings` (short, no closing punctuation, numbered "2.1",
  capitals or title case; not page footers or runs of labels); a PDF
  with no text fails the run with `pdf_no_text` (shown to the reviewer),
  others `pdf_unreadable` / `pdf_encrypted` / `pdf_too_many_pages` (500).
  Tests build PDFs with `tests/pdf_maker.py`.
- **Numbered procedures** (`steps.py`): runs of 2+ consecutive `N. `
  lines are read by code and passed in an `ordered_steps` block. The
  model rewrites each item one for one (`procedure` field, offered only
  with the section's procedure numbers); the operation's check enforces
  one step per item in order (a procedure split over several entries is
  merged back), retried once; each step's quote is set to the original
  item. The entry records `procedure_steps`; fewer kept steps flag it
  "incomplete" (X of N), and approving it needs `acknowledge_incomplete`
  (audited). At most 6 entries per section (extras trimmed, counted).
- **Drafting** (`drafting.py`, AI op `ai_service/draft_kb_entries.py`):
  the chunk is a `<source_chunk>` data block (closing tags escaped), the
  call has no tools. Code then checks: each other step's quote must be a
  passage of the chunk (normalised: case, whitespace, spacing around
  punctuation, doubled backslashes; 15-500 chars) and not stop at a
  lead-in ("On Windows, run:" with more after it: `quote_lead_in`); the
  remaining steps go
  to `check_step_support` (one call per chunk) and unsupported ones are
  dropped; the answer must be a paraphrase (no 12-word run from the
  chunk, <= 60% shared trigrams), otherwise it is removed; a how-to with
  no steps left, or an entry with nothing left, is dropped. Injection
  phrasing in the chunk, or injection/unknown links in the output, flag
  the draft. **Snippets** (`checks.snippet_problem`): up to 3 code,
  config or command lines per entry, copied verbatim from the chunk
  (whitespace aside), <= 600 characters, inside a ``` block / backticked
  span or lines that read as code (never prose), scanned for injection; a
  how-to whose content is a snippet is kept. An entry applies to the
  known or proposed terms its own title, questions, answer and steps name
  (not the model's `applies_to`, which once tagged a live entry with
  every term of its section). Proposed terms need an evidence quote; proposed categories
  a valid name and an entry that asked for them. Both are stored
  `proposed`. The mock AI provider drafts from list items
  (`mock_drafts.py`, registered in `backends.MOCK_RESPONDERS`) so local
  runs show something to review.
- **Runs** (`runs.py`): estimate (fetch + chunk, no model calls: chunks to
  draft x 2 calls) -> start (the caller repeats the estimate; cap = min of
  per-run cap, today's remaining cap, estimate; reserved under an
  advisory lock) -> `execute` as a BackgroundTask, stopping between
  chunks when the next one wouldn't fit (`run_cap` / `daily_cap`), or
  after 3 AI failures in a row. Drafted chunks are skipped by hash, so
  the next run resumes; an unchanged page costs nothing; a document's
  `content_hash` moves only when all its chunks are drafted, and entries
  from chunks no longer on the page become `stale`. Startup fails runs
  left queued/running (`recover_interrupted`). Caps: admin Settings ->
  Knowledge base limits (app_settings `kb`; env `KB_MODEL_CALLS_PER_RUN`
  / `_PER_DAY`), plus runs per hour per manager and one active run per
  source. Every real model call spends the budget, provider and Bedrock
  retries included (`backends.call_budget`, set by `Budget.charging()`);
  a chunk whose retries use up the cap stops the run (`run_cap`) and stays
  undrafted. A run still queued/running counts toward today's cap
  whatever day it started. Near-duplicates (`dedupe.py`, TF-IDF cosine >= 0.8 over title,
  questions, answer, steps vs. every draft/approved entry) are flagged.
- **Review** (`review.py`, `api.py`): support engineers + managers read,
  edit drafts (version-checked; an edited step's quote must still be in
  the chunk and loses its AI check) and propose terms; managers add
  sources (with the public/allowed confirmation, stored with who/when),
  estimate/start runs, approve/reject, confirm/reject/merge terms and
  categories (a confirmed or merged category takes the drafts that asked
  for it). Snippets can be removed in the editor (a new one passes the
  same check). At term review, a hostname in the term's evidence section
  that contains its label but isn't matched by it is shown
  (`review.unmatched_hostnames`); the reviewer adds the alias. The admin gets 403 on all of `/api/kb`. Approving needs
  confirmed terms. Chunk text is purged once no draft from it is left,
  or after `chunk_retention_days`. Everything is in `audit_events`
  (`kb.*`, ids and field names only).
- **Second-pass rules** (`draft_kb_entries._check`, first attempt only,
  one retry with a specific note; then `drafting.py` enforces): a vacuous
  answer ("follow the steps provided") is removed (`answer_vacuous`); an
  entry whose questions all open with the same two words is rejected
  (`questions_one_template`); a reference section (`steps.is_reference`:
  mostly table rows or `- \`param\`` lines) gets no how-to and at most one
  reference/troubleshooting entry, kind `reference` (no steps; never
  grounds a how-to answer). Proposed terms are filtered by
  `checks.term_label_problem`: no "Field:" labels, file names/paths, URL
  bits, or single generic / lower-case words.
- **Model per operation**: app_settings `ai_models` (admin Settings ->
  AI models): drafting defaults to Nova Pro (`DEFAULT_DRAFTING_MODEL`),
  the step check to `BEDROCK_MODEL_ID` (Nova Lite); read by
  `BedrockBackend.model_id()` under `backends.model_task(<operation>)`.
  If the drafting model fails (not a bad reply) on Bedrock, the section is
  drafted once more on the default model, budget allowing
  (`drafting_model_fallback`). The AWS role must allow both models.
- **Licence**: a source's optional `licence_note` (e.g. "CC BY-SA 4.0,
  Odoo S.A.") is copied onto its entries as `source_licence`, next to
  `source_url`, and exported in packs (migration `0005_kb_quality.sql`).
- **Eval**: `scripts/kb_eval.py` drafts the saved fixture pages
  (`tests/fixtures/kb/pages/`: Python venv, GitHub new repository, Odoo
  request time off, with their licences and `expected.json`) with the
  real provider and reports instruction recall (a step's quote or a
  snippet), invented steps, quote failures and cost (`--drafting-model` to
  try another model; `--pages DIR` for pages kept out of git, e.g. a real
  page in `.local/kb-eval/`). `widget_csp` is synthetic: the shape of a
  page whose fix is a config line (`tests/test_kb_regression_widget_csp.py`).
- **UI**: `/kb/review[/<id>]`, `/kb/sources`, `/kb/terms`,
  `/kb/categories` (`pages/KnowledgeBase.jsx`, `components/kb/`); the
  editor shows each step beside its quote and marks the quotes in the
  source section.
- Tests: `test_kb_safe_fetch.py` (SSRF), `test_kb_clean_chunk.py`,
  `test_kb_drafting.py` (checks, procedures, injection),
  `test_kb_quality.py` (lists, completeness, model setting, licence),
  `test_kb_ingest_api.py` (runs, caps, review, roles; runs on Postgres too).

## Chat eval (`backend/evals/`, `docs/CHAT_CONTRACT.md`)

`scripts/chat_eval.sh [--bot-model lite|pro] [--kb demo brightdesk]
[--rerun-failed RUN] [--estimate]`: the chat contract (16 numbered rules)
checked against the REAL Bedrock model. A Nova Lite customer
(`EVAL_CUSTOMER_MODEL`) plays cases generated once per KB entry
(paraphrased, vague, Tanglish/Hinglish with typos, direct or pasted
error) plus per-KB cases (greeting first, topic switch, two near-misses,
off-topic, angry, ok/hmm/thanks, a request for a person, follow-ups)
against `/api/chats` in process, on a fresh SQLite DB with one KB: the
demo DB's approved KB or the Brightdesk fixture (cases cached in
`.local/chat-eval/cases/`). Code rules (`rules.py`) then a Nova Pro judge
(`EVAL_JUDGE_MODEL`, `judge.py`: invented claims, coverage, helpfulness,
tone); a rule 1 judge flag is re-judged, and what stays flagged, or a
rule 3 failure the judge says isn't covered, is "disputed" (listed with
the KB entry side by side in the report). Every Bedrock call is counted
by a wrapped client (`harness.CountedClient`, throttling retried and
counted), hard cap `--max-calls` (3000), the estimate printed first, and a
ledger of all runs against `--budget` (6000) in `.local/chat-eval/`.
Outputs per run: `report.md` (pass rate per rule, overall, worst 10,
disputed), `results.json`, `failures/`. "This reply was wrong" in the web
chat (`POST /api/chats/{id}/feedback`, consent required, `chat_feedback`,
Postgres `0009`) saves the chat; `cases.feedback_cases` replays its
customer turns as permanent cases. Not in the image (`.dockerignore`).
Every run can also be scored with the original rules
(`rules_original.py`, a frozen copy of the baseline's rules; `python -m
backend.evals.rescore RUN ...` prints both side by side, no model calls).
Rule tests: `tests/test_chat_eval_rules.py`.

## Knowledge base (`backend/kb_store.py`)

Tables (SQLite in `backend/db.py` SCHEMA + `_ADDED_COLUMNS`, Postgres in
`migrations/postgres/0003_kb.sql`, `0004_kb_ingest.sql`, `0005_kb_quality.sql`, `0007_kb_snippets.sql`): `kb_entries` (title, answer, kind, snippets (JSON list),
handling, collect, category, source_url / document / chunk / chunk_hash,
stale, supersedes, duplicate_of, status draft|approved|rejected|retired,
reviewer, version), `kb_entry_questions`, `kb_entry_steps` (text + the
quote it is backed by + support_check), `kb_terms` (label, kind
module|variant|platform|integration|edition, aliases, pattern built from
them, status proposed|confirmed|rejected|merged), `kb_entry_terms`,
`kb_categories`, and for the ingester `kb_sources` (with
`public_confirmed_by/_at`), `kb_ingest_runs` (estimated / capped / used
model calls, stop_reason, counts), `kb_documents` (hash only, never the
page), `kb_chunks` (text purged after review/retention).

- Only approved entries are searched; each question is a search
  document and each entry one topic. Every KB write ends with
  `kb_store.changed()` (drops the retrieval and term caches; one worker).
- An entry's `response` for grounding is its answer plus numbered steps
  and its snippets (`kb_store.response_text`). Under an answer grounded
  on it, code adds its snippets as ``` blocks with the source and licence
  (`chat_response.snippet_block`); the chat renderer (`utils/markdown.jsx`)
  shows them as plain text, and the repeat guard ignores them.
- Packs (JSON: approved entries + confirmed terms) move a reviewed KB
  between environments: `scripts/kb_import.py PACK.json` (typed "yes",
  all-or-nothing) / `--export OUT.json`; `--dry-run` validates against
  the database and rolls back, `--counts-only` prints only `KB_IMPORT
  <event> name=number` lines (no pack text), `--count` needs no database,
  and PACK may be `s3://bucket/key`. The pilot imports with
  `scripts/aws_kb_import.sh PACK.json` (a one-off ECS task with the
  service's image, which ships `kb_import.py`; dry run, typed "yes",
  import, service restart; the upload to `kb-packs/` is always deleted).
- Startup prints `KB: <n> entries loaded from the database`; 0 is a
  warning, not an error, and `scripts/aws_smoke.py` reports it.

## Ticket Resolution Agent — live app (`backend/`, `frontend/`)

A four-role app (customer / support engineer / manager / admin) with real
persistence, auth and LLM calls. The bullets below are the detailed design notes per area; the
end-to-end journey is pinned by `tests/test_e2e_helpdesk.py` (real
pipeline, scripted model).

```
Customer/Agent/Admin React portals (frontend/, Vite, :5173)
        |  fetch /api/* (proxied to :8000 in dev)
        v
FastAPI backend (backend/main.py, :8000)
  /api/auth/login (all roles), /api/auth/customer/signup,
  /api/auth/{me,change-password}            JWT (backend/auth.py)
  /api/chats, /api/chats/{id}/{messages,resolve,escalate}   AI chat
  /api/chat-reviews, /api/chat-reviews/{id}   support engineer/manager
  /api/tickets/mine, POST /api/tickets (raise ticket), GET /api/tickets/{id} (thread),
  /{id}/{reply,reopen,attachments}            customer-facing
  /api/staff/tickets[?view=unassigned|mine|recent|open_pending]
  /api/staff/tickets/{id}, /{id}/{claim,status,messages}   support engineer workspace
  /api/manager/overview, /api/manager/departments          manager (read-only)
  /api/incidents[/{id}[/review|/departments|/assignee|/visibility]], /run
  /api/incidents/{id}/resolution/{draft,summary,send}      manager/assigned tech (no admin)
  /api/try-a-ticket                           support engineer/manager (backend/try_ticket.py)
  /api/public/incidents                       public: visibility=public history
  /api/admin/{users,staff,customers,
              departments,settings,audit}            admin (backend/admin.py)
  /api/meta                                   public: status labels, categories + labels, product name
  /api/public/routing-policy                  public, read-only (/docs); /api/debug/... alias
        |
        v
LangGraph pipeline (backend/graph.py)
  fetch_customer_history -> retrieve_kb_candidates -> classify_ticket
                                                     -> decide_route
                                                              |
                        {generate_response |
                         ask_clarifying_question | human_queue}
        |
        v
SQLite (backend/ticketapp.db, auto-created, gitignored)
  customers / staff / admins / tickets / ticket_messages / attachments /
  departments / audit_events / app_settings / chat_* / incident_*
  (incl. incident_deliveries, incident_memory) / kb_*
```

- **KB grounding — `retrieve_kb_candidates`** (`backend/graph.py`,
  `backend/kb_retrieval.py`): runs before classification, on every
  turn. Scores the ticket text (only the customer-authored lines of a
  multi-turn transcript; the latest message first, `graph.retrieval_query`)
  against the approved entries' questions via TF-IDF-weighted cosine
  similarity over word tokens (each entry scores the better of the query
  and the query plus the other names of each confirmed term it names,
  `topic_terms.with_names`: "Content Security Policy" finds "CSP"), with a stopword filter (formally phrased
  KB questions make filler words anomalously high-IDF). A best match
  below `KB_MIN_SCORE` (default 0.35) is no match; then (not for a vague
  message) one model call rewrites the query in the KB's own words from
  the entries' titles (`ai_service/rewrite_query.py`, "" when no topic
  fits) and the same search runs again; the rewrite (`query_rewrite`)
  counts as the customer's words for the how-to subject check. Off in
  tests unless a test turns it on (`tests/conftest._no_query_rewrite`). The top 2-3
  candidates ground `classify_ticket`'s prompt (few-shot category
  evidence; a strong match, `kb_retrieval.STRONG_MATCH_SCORE`, raises a
  conservative raw LLM confidence), `ask_clarifying_question`'s prompt
  (the specific candidate topics), and `generate_response`'s prompt (the
  top candidate's answer + steps). **Terms** (`backend/topic_terms.py`,
  confirmed `kb_terms` only, none built in): an entry that applies to a
  term the customer hasn't mentioned never grounds a reply and is passed
  as an "unconfirmed topic" to ask about (`graph.grounding_candidates`);
  one for another term of the same kind than the customer named (the
  Android guide for an iPad) is skipped (`names_another_variant`).
  Modules/variants (`topic_terms.SUBJECT_KINDS`) are "which part of the
  product": `chat_response.subject_question()` lists them, and with none
  confirmed there is nothing to ask. An entry's `kind` (how-to /
  troubleshooting) beats the question-wording guess
  (`request_kind.is_fault`). An approved entry with `handling:
  escalate_with_info` that grounds a reply gets
  `chat_response.info_request` (numbered steps, never a question, then
  its `collect` list and a fixed safety note) and the chat / ticket goes
  to the support team in the same turn (`needs_info`, reason
  `kb_needs_info`). The category picked at chat/ticket start narrows
  grounding only, never classification or routing; prompts never ask for
  identifiers (the AI has no account access) but for the product area,
  exact error, screen/step, what was tried, and the chat filter swaps
  identifier requests for one. No embedding model. Covered by
  `tests/test_kb_retrieval.py`, `tests/test_topic_terms.py`,
  `tests/test_needs_info.py`, `tests/test_ask_clarifying_question.py`.

- **decide_route's third branch — "clarify"** (`backend/graph.py`): a
  *non*-high-risk ticket below the base confidence bar doesn't escalate
  blind anymore. It routes to `ask_clarifying_question`, which (per KB
  grounding above) asks one targeted question naming the actual
  candidate topics rather than a generic "tell me more" — stored via
  `ai_response` so it flows through the same
  `chat_messages`/`ChatSession.jsx` path as a normal AI reply, no
  separate frontend plumbing needed. `tickets.clarification_attempts`
  (new column, default 0) tracks the count; each chat reply re-invokes
  the graph, so `classify_ticket`/`decide_route` re-run on the fuller
  transcript and can resolve to `ai` once it's no longer ambiguous.
  After `max_clarification_attempts` rounds (default 1, routing setting)
  still below the bar, `decide_route` routes `ai`: `generate_response`
  answers from the matched KB entry or says "no guide" and raises the
  ticket (never a bare hand-off, never a second question). Once the
  question was asked, an entry held back only because the customer didn't
  name its module (not a platform/variant) is usable
  (`graph.grounding_candidates`).
  **High-risk categories (default ACCOUNT/BILLING/DATA) below their stricter 90% bar
  never get KB-topic clarification or an AI answer**: an
  `escalate_with_info` KB entry gives its steps + collect list + safety
  note and raises the ticket; a vague first report (`clarification_attempts`
  0, not a how-to, no error reported) gets ONE question
  (`chat_response.clarify` with `high_risk`: where they sign in, what is
  on the screen, what a vague phrase meant; no KB topics, no causes), and the
  next turn still below the bar goes to a human; anything else goes to a
  human immediately — checked *before* the clarify branch (even
  mid-clarification, discovering a ticket is actually high-risk and still
  uncertain forces an immediate human handoff). **A how-to**
  (`backend/request_kind.py`: add / set up / configure, no fault words)
  is never asked "are you referring to...?". It gets at most ONE fixed
  question (`graph.how_to_question`, no model call, checked right after
  the escalation-tag override): with no subject at all ("how do I add
  it") what exactly and in which part of the product
  (`HOW_TO_SUBJECT_QUESTION` with the confirmed modules, or
  `HOW_TO_GENERIC_QUESTION`), or, when the only guides on its subject
  apply to terms not named (the Android / iOS app guides), which one.
  Once asked (`asked_how_to_question`, found in the transcript) it is
  never asked again, and the answer ("an expense claim", "not sure") is
  still the how-to.
  Otherwise `generate_response` answers from a how-to KB entry on the
  customer's subject (`graph.on_customer_subject`: half the customer's
  words, or a strong match whose question names their main subject, so
  extra words don't hide a guide while "an overtime report for leave
  approvals" isn't the apply-for-leave entry; and the entry must name
  the customer's task, their first task verb or a same-task one
  (`graph.does_the_task`: change/edit/modify, cancel/withdraw, export/
  download...; generic verbs don't count), so "can I change my leave
  dates" isn't the apply-for-leave entry either; `kind: how-to` guides rank
  first; troubleshooting entries never ground it), or, with none, says "I
  don't have a guide for that yet" and raises the ticket
  (`NO_KB_REPLY_*`, no model call, `needs_info.reason = "kb_no_match"`,
  `graph.handoff_reason`). Flows: `tests/test_how_to_flow.py`.
  **No answer without a guide**: a report (not a how-to) no usable KB
  entry covers is clarified (`decide_route`, up to max rounds), then gets
  the same "no guide" reply and ticket; when the matched entry doesn't
  cover the latest message the model replies `NOT_COVERED`
  (`chat_response.NOT_COVERED`) and `generate_response` hands off the same
  way. **Values** (`grounding.ground_values`, every chat/email reply): a
  sentence carrying a domain/URL, a directive with its whole source list,
  quoted or backticked text, a path, or a version/port/limit number that
  neither the grounding entry nor the customer's own messages contain is
  dropped (logged at WARNING with the sentence and the value); a reply
  losing most of its text is regenerated once.
  **Instructions** (`grounding.ground_instructions`, every chat/email
  reply): a sentence or line telling the customer to do something ("Try
  restarting the app", "Have you tried disabling the firewall?") must be
  backed by ONE passage of the grounding entry (a sentence or step, or two
  adjacent ones) holding its action verb (or a same-action verb:
  pick/choose/select...) and >= 50% of its content words, or >= 80% of
  them; never by the customer's own words. Unbacked ones are dropped and
  logged; a procedure that loses a step, or a reply that loses most of its
  text, is regenerated once (`_STEPS_NOTE`), then the entry's own answer
  (`chat_response.kb_answer`). An answer's sentence or
  step that restates an earlier sentence (>= 60% of its 5+ content words,
  `grounding.drop_restatements`) is dropped and logged too. A
  lead-in promising steps that don't follow ("Here's how:") is removed
  (`grounding.strip_dangling_lead_ins`). Steps in an answer that the top KB entry
  doesn't support are dropped (`ai_service/grounding.py`), the exact
  error message is asked for only after the customer reported an error,
  and how-to answers lose the "if you encounter issues..." line.
  Sample conversations: `tests/test_live_chat_review.py`. The escalation-language-tag hard override is checked
  before even that, and always wins. A ticket sitting in a clarify
  round has status `pending_customer` (distinct from `open`, which means
  waiting on the support team). Covered by `tests/test_decide_route.py` (pure-function
  tests, no LLM calls).

- **AI chat = chat sessions, separate from tickets** (`backend/chats.py`,
  `frontend/src/components/ChatSession.jsx`; reconcile sub-stage A).
  `chat_sessions` (`active | resolved | escalated | abandoned`) +
  `chat_messages` (`customer | ai`). Every customer message re-invokes
  the graph with the full transcript (after the per-message gates in
  `backend/conversation.followup_gate`, shared with ticket replies).
  **Resolved**: only on the customer saying it is solved ("that worked",
  "all set": `closing_ack.confirms_solved`, or the "My issue is solved"
  button); a bare "thanks" / "ok" / "got it" / "hmm" gets `chats.ACK_REPLY`
  and the chat stays open; tickets follow the same rule (a bare "thanks"
  on a resolved AI ticket is kept with no reply, `main._run_followup`). An
  open chat with no message for `CHAT_IDLE_TIMEOUT_MINUTES` (default 30) is
  closed as `abandoned` with `chats.IDLE_CLOSED_MESSAGE` (no ticket),
  checked lazily when the chat or a chat list (customer or staff) is
  loaded or written (`chats.close_idle_chats`, `_close_if_idle`). A
  greeting ("hi", `request_kind.is_small_talk`) gets `chats.greeting()`
  (no model call), and the first real message replaces it as the chat's
  `issue`. "I want to talk to a human" (`handoff_signals.asks_for_human`)
  escalates at once. Off-topic (category OTHER, no KB candidate, no term
  or product name: `graph.off_topic_reply`) gets a fixed brief reply, no
  ticket. The session closes with
  an AI resolution summary and a `chat_reviews` row
  (`pending_review -> verified -> closed`, support engineers/admin via
  `/api/chat-reviews`, "Chat Reviews" tab); **no ticket is created**.
  **Escalated** (customer accepts a hand-off, AI admits a limitation,
  decide_route says human, or the customer clicks "Raise a ticket"):
  creates an unassigned `open` ticket (`ticket_type = 'chat'`,
  `chat_session_id` link) carrying the AI hand-off brief
  (`ai_summary`: issue / tried / findings / unresolved questions;
  `ai_suggestions`: next steps — staff-only, never returned by customer
  endpoints; the brief text is also appended to `ticket_text` after
  `ESCALATION_MARKER` so the queue shows it). The customer is told the
  ticket reference; the transcript stays in `chat_messages` and the
  customer's ticket view shows it as a collapsible "Chat transcript".
  **AI failure** never changes chat state: the customer's message is
  kept, everything after it is rolled back (SAVEPOINT), the response
  carries `ai_error`, the bot replies `chats.OUTAGE_REPLY` (offers a
  ticket: "yes" raises it; never counts as an answer for "My issue is
  solved"), and "Raise a ticket" still works. The chat eval marks a
  conversation with a provider failure (`harness.infra_error`: kind
  throttling / timeout / network / access_denied / config) `infra_error`
  and leaves it out of the score. Summaries come
  from `backend/ai_service/summarize_conversation.py` (validated pydantic output,
  retry once, deterministic fallback marked `source: "fallback"` — set by
  code, never the model). Pre-session chat-type ticket rows are migrated
  in place by `db._migrate_chat_tickets`. Covered by
  `tests/test_chat_sessions.py`, `tests/test_chat_followup_gates.py`,
  `tests/test_handoff_escalation.py`.
  **Bare closing acknowledgment short-circuit** (`backend/closing_ack.py`):
  a follow-up after an AI answer (chat) or on a `resolved` AI-handled
  ticket (email-style reply) isn't automatically re-classified if it's an unambiguous acknowledgment
  ("thanks", "got it", "that worked", ...) — "thanks" isn't a support
  request and used to get classified with near-zero confidence and
  wrongly escalated to a human even though the issue was solved. The
  check is deliberately conservative: any negation/continuation signal
  ("but", "still", "not"), a question mark, or more than a handful of
  words falls through to the normal pipeline instead, so "thanks, but
  it's still not working" (or any genuinely new content) still gets
  reclassified and can re-open or escalate normally. A bare
  acknowledgment resolves a chat (see above) or closes a ticket
  (`status = "closed"`, with a visible system message); further
  messages get a 400. Covered by `tests/test_closing_ack.py` (pure
  function) and `tests/test_chat_followup_gates.py` (endpoint-level,
  stubbed graph, real temp SQLite DB via FastAPI's TestClient).
  **Continuation short-circuit** (`graph.is_continuation_of_prior_response`,
  checked second, after the closing-ack check): a follow-up that refers
  back to the AI's own last reply ("what is the difference", "can you
  elaborate") is a continuation of the *same* answered thread, not a
  new ticket to triage — classify_ticket judges each message's own
  classifiability, and a short follow-up fragment has almost no
  standalone content, which used to collapse decide_route's confidence
  and wrongly escalate an on-topic question the conversation already
  makes answerable. A cheap, targeted LLM call (`prior AI reply` +
  `new message` -> `{"is_continuation": bool}`) decides this; a true
  result skips classify_ticket/decide_route entirely for that turn and
  calls `generate_response` directly, grounded via
  `retrieve_kb_candidates_for_continuation` (searches on the prior
  reply's own content, not just the uninformative new fragment — the
  same signal-to-noise problem `retrieve_kb_candidates`'s stopword
  filter solves, here solved by widening the query instead) and
  `generate_response`'s new `continuation=True` prompt note (treat the
  transcript as an ongoing exchange to build on). **The escalation-
  language hard override still wins even over a topical continuation**:
  `graph.has_escalation_language` gates the check first, so "thanks,
  but it's still not working" — topically a continuation, but carrying
  negation — is never even passed to `is_continuation_of_prior_response`
  and instead falls through to the normal pipeline, where the hard
  override escalates it as it always has. A genuinely new/different
  message (same LLM call, negative result) likewise falls through
  unchanged. A bare request for the steps again after an answer ("ok how
  to solve it", "what next", "steps"; `request_kind.asks_for_steps`, the
  whole message) is a continuation without the model check, and
  `generate_response` re-presents the top entry's numbered steps and
  snippets by code (`chat_response.steps_again`, no model call); an entry
  with neither gets a normal continuation answer. "What are the sources?"
  (`request_kind.asks_for_sources`) after an answer gets the guide's
  title, source page and snippets by code (`chat_response.sources`). Any
  other follow-up first gets one yes/no call, does the guide answer the
  latest message (`chat_response.covers_latest`); if not,
  `FOLLOWUP_NOT_COVERED` (the guide doesn't cover it; a ticket offer, "yes"
  raises it), never an answer. The check is off in tests unless a test
  turns it on (`tests/conftest._followups_covered`).
  Covered by
  `tests/test_continuation_check.py`
  (stubbed-client prompt/parsing tests) and
  `tests/test_chat_followup_gates.py` (endpoint-level).

- **Customer portal + ticket model (Stage 2)**
  (`frontend/src/pages/CustomerPortal.jsx`, `components/TicketThread.jsx`):
  two request cards — **Start a chat** (pre-chat form -> live
  `ChatSession`, see chat sessions above) and **Raise a ticket** (subject,
  category, priority, description, drag-and-drop attachments;
  `POST /api/tickets`, `ticket_type = 'ticket'`, no chat). Right panel
  has **My tickets** (tickets, incl. escalated chats with a Chat badge)
  and **Chats** (chat history, resolved ones read-only), with All/Open/Resolved/Escalated
  filters ("Escalated" = `route == 'human'`), search, unread dot
  (`tickets.customer_last_read_at`) and a Chat badge. Ticket detail is an
  email-style thread with a reply composer (`/reply` runs the same
  follow-up gates as `/chat` while the AI owns the ticket; once it's with
  the support team the reply is just appended) and Reopen on resolved
  tickets. **Statuses** (`db.TICKET_STATUSES`): `open`, `in_progress`,
  `pending_customer`, `resolved`, `closed` (legacy `awaiting_reply` /
  `assigned` are migrated in place). For `ticket_type = 'ticket'`,
  `generate_response`/`ask_clarifying_question` get
  `reply_format='email'`: the LLM writes only the body and
  `email_utils.format_email_reply` adds "Hi <first name>," + closing +
  "Regards, Support Team"; AI replies are also emailed via
  `email_utils.send_email` when SMTP is configured (silent no-op
  otherwise, sent as a BackgroundTask). A pipeline failure on a new ticket
  still creates it, queued for a human; an AI failure on a reply to an
  AI-handled ticket hands it to the team the same way, replying "A person
  will reply here soon." (`main._escalate_after_failure`, reason
  `ai_unavailable`). **Attachments**
  (`POST /api/tickets/{id}/attachments`, `attachments` table): max 5 per
  message (counted under a write lock), 10 MB each, png/jpg/pdf/txt/log with the contents checked
  against the extension, stored under `db.uploads_dir()` (DB_PATH's
  parent `/uploads`) with random names. Covered by
  `tests/test_customer_tickets.py`.

- **Role layout** (`layout/nav.js`, `pages/{Admin,Manager,Technician}Portal.jsx`).
  **Admin: people and system only** — People (Users, Departments) ·
  System (Settings incl. SLA targets, Activity log); 403 on every ticket,
  dashboard, SLA-report, chat, chat-review, incident and Try-a-ticket
  endpoint (`tests/test_role_scope.py`). **Manager: own department only**
  (`staff.department_id`; a ticket or chat is in it when the department
  owns `COALESCE(category, requested_category)`), lists, counts and
  direct ids alike (`backend/manager.py`, `staff_tickets._ticket_for_staff`
  403, `chats._chat_scope` 404): Overview (Dashboard "Dashboard ·
  <department>", SLA) · Work (Department tickets with reassign + priority,
  Chats, Chat reviews, Incidents) · Knowledge base (+ Try a ticket).
  Reassign goes only to support engineers whose `department_id` is the
  manager's (support engineers may now "work" one department, set under Users).
  A Platform Lead (see Manager types) has every department, a department
  dropdown in the top bar and Teams.
  **Support engineer**: My work (Dashboard of their own tickets only, Tickets
  with tabs + counts + filters + Claim, Chats) · More (Chat reviews, KB
  review queue, Try a ticket); assigned incidents stay at
  `/technician/incidents`. **Chats** (`GET /api/staff/chats[/{id}]`,
  `StaffChats.jsx`): read-only transcripts, support engineers + managers;
  "Take this chat" is a placeholder. **Periods** (`backend/periods.py`,
  `components/dashboard/PeriodSelect.jsx`): Today … This year, IST, weeks
  from Monday, default This week. Covered by
  `tests/test_department_scope.py`, `tests/test_periods.py`.
- **Users, reports, SLA** (`backend/admin_users.py`,
  `backend/admin_reports.py`, `backend/sla.py`; `UsersPanel`,
  `components/dashboard/`, `SlaPanel`, `OneTimePassword`, `ui/SlaChip`).
  **Users** (admin-only): one list of customers,
  support engineers and managers (`/api/admin/users`, same functions as the
  older `/api/admin/staff` and `/api/admin/customers`); never the admin
  (env-seeded) and never role `admin`. Create and reset generate the
  temporary password server-side (`auth.generate_temporary_password`),
  returned once with `Cache-Control: no-store`, stored only hashed, never
  in a list or the audit log; forced change at first sign-in.
  Deactivated users can't sign in, tickets kept. **Reports**
  (`admin_reports.py`, no router; `scope_sql(categories)` limits them):
  `dashboard_data` (KPIs now, created/resolved per IST day, workload,
  open by priority, avg first response) and `sla_data` for
  `/api/manager/{dashboard,sla}`, `technician_data` for
  `/api/staff/dashboard`; aggregated
  in Python so it runs the same on SQLite and Postgres. **SLA** (settings
  section `sla`, off by default): per priority a first-response and a
  resolution target; a ticket gets targets and due times at creation
  (`ticket_lifecycle.record_created` -> `sla.on_created`), a priority
  change recalculates from creation (`set_priority`); first response =
  first public reply by a staff member (or the AI on an AI-handled
  ticket), via `conversation.insert_ticket_message`; the resolution clock
  pauses in Pending Customer and Resolved/Closed (`set_status` ->
  `sla.on_status_changed`). Calendar 24x7 only; `sla.add_working_time` /
  `working_seconds` are where business hours go. States on_track /
  at_risk (`at_risk_percent`, default 75) / breached / met / paused;
  `sla` is on staff ticket payloads, never customer ones. New
  ticket columns (`first_response_at`, `resolved_at`, `sla_*`):
  `db._ADDED_COLUMNS` + backfill for SQLite,
  `migrations/postgres/0002_sla.sql` for Postgres. Covered by
  `tests/test_admin_area.py` (run on Postgres with
  `DB_BACKEND=postgres`).
- **Admin portal** (`frontend/src/pages/AdminPortal.jsx`): the single
  admin (see Auth). Sections **Users**, **Departments**
  (`components/DepartmentsPanel.jsx`: create/edit/delete
  departments and their KB-category mapping — each category belongs to
  at most one department, enforced server-side), **Settings** and
  **Activity log**, each its own route (`/admin/<section>`). The routing
  policy is public, read-only at `/docs/routing-policy`.

- **Frontend design system** (`frontend/src/styles/theme.css`,
  `src/ui/` shadcn-pattern components on Radix, `src/layout/AppShell.jsx`,
  `PRODUCT.md`): Tailwind v4, Lucide icons, Recharts, self-hosted IBM Plex
  Sans/Mono. "Framed sheet" layout: a 48px top bar on the tinted frame and
  the page on a white sheet with a 1px edge. No sidebar by default: the
  menu button (far left) opens the role's full menu (`layout/nav.js`
  `groups`) as a slide-in panel (Radix Dialog: focus trapped, Escape /
  scrim / picking a screen closes it, always starts closed); the top bar
  keeps the main screens (`primary`), the page title, the theme menu and
  the user menu, and under 768px those fold into the panel. **Status
  language** (`ui/status.jsx`, `lib/statusMeta.js`, theme `--status-*`):
  one colour + icon + word per status everywhere: New (open, nobody
  assigned) grey, Open blue, In progress teal, Pending customer violet,
  Resolved green, Closed slate; SLA is a clock + words with no fill (amber
  only for at risk); priority is signal bars, red only for urgent; the
  legacy StatusChip / SlaChip render the same. Support Bot replies (chat
  and ticket threads) get the `--bot-bg` tint, a left rule, a bot icon and
  "Automatic reply"; staff replies stay plain. **Dashboard**
  (`components/dashboard/Dashboard.jsx`, one for managers and support
  engineers): the period selector and ONE line of counts, "Created
  <period>" (created in the period by current status, adding up to Total:
  Total, New (unassigned), Open, In progress, Pending customer, Resolved,
  Closed; then SLA breached and at risk; `by_status`, `created_sla`); a
  count filters the list below (`/api/manager/tickets` or
  `/api/staff/tickets?view=mine` with `period`, `status=new`, `assigned`;
  same role scope; an SLA count sends `sla=breached|at_risk`, filtered on
  the server before the list limit; the New
  list shows a New chip); then charts for the period (by priority
  `by_priority`, by status, created vs resolved `over_time`; text
  alternatives: the bars' numbers are text, the day chart has a hidden
  table); managers then get "Support engineers" (`technician_workload`). Ticket lists (`components/TicketRows.jsx`): a table
  from 768px, two-line items on phones. **Public**: `/` landing page for
  signed-out visitors (`pages/Landing.jsx`, product name from /api/meta,
  "Runs on Sahayak"), `/login` and `/signup` (`pages/Login.jsx`: show /
  hide password, field errors, 429 countdown from Retry-After); `/docs`,
  `/incidents` use `PublicShell`. **Setup** (`components/SetupWizard.jsx`):
  `/admin/settings` opens on a 5-step setup (product, categories and their
  departments, each support engineer's department with the count still missing,
  each manager's type and department with the count still missing (a
  Platform Lead needs none), done) while the product is unnamed and not skipped in this browser;
  "Run setup again" brings it back. Colour only on data, status and the
  one primary action; every text token >= 4.5:1 in both themes (contrast
  table in `docs/DESIGN_SYSTEM.md` section 0).
  The UI names the product "Help Desk" and the bot "Support Bot" (no
  third-party brand in user-visible text). The portal shown is picked
  from the role inside the token (`lib/tokenRole.js`, `api.getRole`), never
  a separately stored role, and a sign-in/out in another tab reloads the
  others (`api.onSessionChange`): a stale stored role once showed the admin
  the support engineer workspace, all 403s (`tests/test_frontend_session.py`).
  Pages not yet rebuilt still use
  the old stylesheets, imported into a lower cascade layer
  (`src/styles/legacy/`) until they are converted.

- **Routing policy** (`backend/graph.py`): base confidence 75%,
  high-risk categories (default ACCOUNT/BILLING/DATA) need ≥90%;
  `decide_route` tries `clarify` first for non-high-risk categories
  (see above) — high-risk categories below their bar still
  escalate immediately, and the `offensive_language`/`negation`
  language tags force immediate escalation regardless of confidence,
  category, or clarification state. Tags come from the customer's latest
  message only (`graph._detect_language_tags`): profanity (not frustration:
  "useless" is answered), and, only after an AI reply, a report that it
  didn't work ("still not working", "same error"). `coordinated_syntax` is
  no longer detected (it handed off every long message; the chat eval
  found "isn't working" in first reports handed off the same way).
  A confident report no KB entry covers is clarified, then handed off
  with "no guide" (never answered from general knowledge).
  `classify_ticket` runs a small regex heuristic to populate
  `language_tags`. `/api/public/routing-policy`'s `decision_order`
  (shown live at `/docs/routing-policy`, public; `/debug` redirects there)
  is the source of truth for the exact precedence — read from
  `graph.py`'s constants, not hardcoded in the frontend.
- **Agent-facing ticket text** (`frontend/src/utils/parseTicketText.js`,
  `TicketTextDetail.jsx`): `ticket_text` sometimes has a chat case
  summary appended (the `--- Escalated after chat ---` marker
  `main.py`'s chat handler writes). The Queue/My Tickets list preview
  shows the case summary when present (more useful for scanning than the
  start of the raw concatenated string), and expanding a row (click the
  row, chevron toggles) renders "Customer's original message" and "AI
  summary" as distinct labeled sections instead of one run-on string.
  Tickets that escalated without a chat (e.g. an immediate high-risk
  escalation) have no marker, so `summary` comes back `null` and only
  the original-message section renders — no empty summary block. Same
  parsing reused in the manager's Department tickets table.
- **AI service** (`backend/ai_service/`, reconcile sub-stage C): every
  model call goes through it — one module per operation
  (`categorize_ticket`, `chat_response` [answer / clarify /
  is_continuation], `summarize_conversation`, `summarize_ticket`,
  `suggest_steps`, `correlate_incidents`, `summarize_incident`,
  `draft_post_incident`, `incident_question`), each
  with pydantic input/output schemas in `schemas.py`. `provider.py` is
  the only entry point (`complete_json` / `complete_text` -> `complete`
  -> the backend chosen by `AI_PROVIDER`, `backends.py`: `quickml_appsail`
  [Catalyst QuickML LLM Serving REST call, one stateless prompt string,
  authenticated with the admin credential AppSail injects into each
  request — captured per request by `main._CatalystRequestContext` into
  the `backends.appsail_credentials` contextvar (`AppSailCredentials`,
  secrets hidden from repr), never stored globally or logged; exact
  request in `docs/quickml-appsail-call.md`; response text at
  `data[0].data`; no SDK `ask_llm` exists and the Zoho self client is
  blocked, so this only works on AppSail], `openai_compatible`, `azure`
  [until Phase 4 C6], `mock` [default when unset; minimal schema-valid
  JSON; the only option locally]).
  Instructions in the system prompt, untrusted text in delimited data
  blocks (closing tags escaped); single-prompt backends flatten to
  Instructions / Data / Correction / Response sections. Replies are
  cleaned (`<think>` reasoning and code fences stripped, the JSON object
  extracted; a plain-text reply wrapped as `{"response": ...}` unwrapped),
  validated (+ semantic `check`, e.g. correlation ids must be
  from the input), retried once with a note giving the validation error
  paths (never the rejected values), then `AIError`. Provider errors are
  never retried, except Bedrock throttling/timeouts and connection errors
  (kind `network`, e.g. a local proxy dropping a call; one retry after ~1 s
  plus jitter, in `BedrockBackend.generate`); a failed continuation check
  sends the message down the normal pipeline instead of failing the turn; QuickML codes are mapped (`INVALID_ENDPOINT_KEY` — an
  HTTP 500 — and `ORGID_HEADER_UNAVAILABLE` are `ConfigError`s logged at
  ERROR). No embeddings with
  QuickML: incident grouping uses lexical TF-IDF (`incidents._lexical_vectors`,
  `INCIDENT_SIMILARITY` default 0.15). `scripts/ai_smoke_test.py` runs the
  key prompts against the real provider. Provider errors log the
  exception type only and are re-raised without the chained cause.
  `graph.py` keeps routing policy + KB grounding and calls the service;
  callers treat `AIError` as "AI unavailable" without changing state.
  Hand-off briefs (`conversation.handoff_brief`) = summary (tidied by
  `summarize_conversation.tidy_handoff`: no "N/A" items, "Already tried:
  Nothing stated yet", no findings that restate the issue) + next steps
  only from KB entries matching the customer's own words
  (`graph.handoff_kb_candidates`; model steps the entry doesn't support
  dropped, else the entry's sentences; "No KB match - needs triage"
  without a match), each with its own fallback. `.env` is loaded once in
  `backend/__init__.py` (before it was loaded after `auth` read
  `JWT_SECRET`, so local dev silently used the default secret). Tests
  can't reach the provider (`tests/conftest.py`); covered by
  `tests/test_ai_service.py`.
- **AI incident correlation** (reconcile sub-stage D; `backend/incidents.py`,
  `frontend/src/components/IncidentsPanel.jsx`). After every new ticket
  or chat escalation (BackgroundTask) and on "Check now"
  (`POST /api/incidents/run`): tickets from the last
  `INCIDENT_WINDOW_HOURS` (not in a dismissed cluster) are grouped by
  component area — the department owning their category (the classifier
  often splits one outage across SETUP/ISSUE), else the
  category — optionally split by embedding similarity
  (`AZURE_OPENAI_EMBEDDING_DEPLOYMENT`, `INCIDENT_SIMILARITY`). Groups
  with `INCIDENT_MIN_TICKETS`+ tickets from 2+ customers go to
  `ai_service.correlate_incidents`; groups already fully inside an open
  cluster aren't re-sent. Related tickets join the overlapping open
  cluster or a new one (`incident_clusters`, `incident_tickets`); tickets
  are only linked, never changed. Departments: owners of the tickets'
  categories + the AI's (normalised) suggestions, only at confidence >=
  `INCIDENT_ROUTING_CONFIDENCE`, else `needs_routing`. Manager/admin
  corrections (`source = 'manager'`) survive AI re-runs. Review:
  confirm / investigate / dismiss with a note -> `incident_reviews`.
  Managers see clusters linked to their departments plus unrouted ones;
  a linked ticket outside their department is listed without subject or
  customer and can't be opened (`can_open`, same rule as the workspace). Customers on a confirmed cluster's
  tickets get a neutral `incident_notice`. No reply-to-all fan-out.
  Covered by `tests/test_incidents.py`.
- **Post-incident summary + incident memory** (`backend/incident_resolution.py`,
  `backend/incident_memory.py`, `backend/timeutil.py`,
  `ai_service/draft_post_incident.py`, `ai_service/incident_question.py`,
  `frontend/src/components/IncidentResolution.jsx`,
  `pages/IncidentHistory.jsx`). Incident statuses gain `resolved`;
  new cluster fields `started_at` (earliest linked ticket), `resolved_at`
  (UTC, shown in IST), `resolution_note`, `root_cause`,
  `customer_summary`, `internal_summary`, `summary_status`
  (none/draft/approved/sent), `visibility` (affected_only/public),
  `assigned_technician_id`, `resolved_by`. Only a **confirmed** incident
  can be resolved, by a manager who can see it, the admin, or the
  support engineer it's assigned to (`PUT /api/incidents/{id}/assignee`;
  support engineers see only assigned incidents). The draft op gets the
  incident's facts + the staff note only; code composes the When line
  and the Cause line (staff root cause verbatim or "still being
  reviewed"), and `_check` rejects model text with times/dates/relative
  days or cause claims. Approve & send never runs automatically and must
  echo the saved text; each linked ticket is delivered in its own
  transaction with an `incident_deliveries` row (sent tickets skipped,
  failures recorded, re-send retries failures only), posted as a public
  `staff` message with no author (shown as "Support Team",
  `incident_update` flag in the customer thread); real email only via
  `Outbox` when `EMAIL_ENABLED`. Optional mark-Resolved via
  `ticket_lifecycle`; never close/merge. `incident_memory.remember()`
  snapshots confirmed/resolved incidents (forgets dismissed) for
  `INCIDENT_MEMORY_DAYS` (`app_settings` incidents.memory_days).
  `answer_incident_question` runs first in `chats._respond` and
  `main._run_followup` (keyword gate -> AI parses an IST time window ->
  `find_matches` only over memories the customer is linked to or that are
  public -> fixed templates + stored summary; the model never writes the
  answer). `GET /api/public/incidents` (no auth) lists public ones.
  Covered by `tests/test_incident_resolution.py`.
- **Admin console, settings, audit** (reconcile sub-stage E;
  `backend/admin.py`, `backend/app_settings.py`, `backend/audit.py`).
  All admin endpoints live in `admin.py` (admin role on every one):
  simulator, Team (`PATCH /api/admin/staff/{id}`:
  name/email/role/department; a support engineer with open tickets can't change
  role; a role change invalidates their token), Customers (create with a
  forced password change, edit, deactivate — live sessions blocked —
  reset password), departments, settings, audit log. **A manager belongs
  to one department** (`staff.department_id`; the legacy
  `manager_departments` table is read once by the migration — first
  mapping kept — and no longer written); a support engineer may work one
  (optional; the manager can assign them there).
  **Settings** (`app_settings`): `routing` (confidence bars, high-risk
  categories, escalation language tags, max clarifying rounds — read by
  `graph.decide_route` on every decision), `incidents` (window, min
  tickets, similarity, routing confidence — admin value > `INCIDENT_*`
  env > default), `statuses` (display labels only; the five statuses are
  fixed; served by public `GET /api/meta` and loaded by `main.jsx` before
  render). Cached in memory per process (loaded at startup, refreshed on
  save). **Audit log** (`audit_events`): ticket status/assignment changes
  and claims (via `ticket_lifecycle`), incident reviews and department
  corrections, chat review updates, staff/customer/department/settings
  admin changes, password changes and failed logins — ids, statuses and
  field names only, never bodies or passwords; filterable at
  `GET /api/admin/audit` (Activity tab). **AI failures**
  (`backend/ai_failures.py`): every failure of a chat turn, ticket reply
  or new ticket is audited as `chat.ai_failure` / `ticket.ai_failure`
  with kind (throttling, timeout, network, access_denied, validation, parse_schema,
  filter_rejected, config, unknown), error code name, attempts, latency,
  operation and outcome (`failed` = the customer saw "AI unavailable";
  `regenerated`/`fallback` = our own check rejected a reply and the chat
  recovered with a regenerated reply or a fallback question); never
  provider text or customer text; admin view `GET /api/admin/chats/{id}`.
  Chat replies also get a repeat guard (>= 80% word overlap with one of
  the last two AI replies: regenerate once, then a different question or
  a ticket offer), a vague-message open question (no symptom yet: no KB
  grounding, no model call), and a latest-message-first KB query
  (`graph.retrieval_query`). **Real email is off** unless
  `EMAIL_ENABLED=true` + SMTP (`Outbox.flush` / `email_utils.email_enabled`).
  Attachments are only served by the authorised download endpoint (no
  static mount). Covered by `tests/test_admin_console.py`.
- **Auth / roles** (`backend/auth.py`): customer, support engineer, manager,
  admin. **Names**: people read "Support Engineer" ("Technical Support
  Engineer" in the Users role dropdown); the role value stays `technician`
  in the database, tokens, URLs (`/technician`) and API paths. Tables: `customers`, `staff` (support engineers + managers, `role`
  column, `active`, `must_change_password`), `admins`. One login page /
  `POST /api/auth/login` for every role; the token carries the role and
  the frontend routes to `/customer`, `/technician`, `/manager` or
  `/admin`. Only customers can sign up publicly; staff are created by the
  admin with a temporary password and must change it on first login
  (`require_role` blocks every other endpoint until they do). Exactly one
  admin, created on startup from `ADMIN_EMAIL`/`ADMIN_PASSWORD`
  (`auth.ensure_admin`, never overwrites an existing admin); outside
  production a dev fallback is used with a loud warning, and
  `APP_ENV=production` refuses to start without them. Staff/admin
  dependencies re-read the DB per request, so deactivation takes effect
  immediately. Emails are unique across all three tables. The legacy
  `agents` table / `assigned_agent_id` column are migrated in place to
  `staff` / `assigned_technician_id` by `db.init_db()`. Dev-only demo
  manager (Tech Lead) + support engineer + Platform Lead
  (`seed_data.DEMO_PLATFORM_LEAD`, no department) are seeded by
  `seed_data.seed_demo_staff`, never in production.
  bcrypt-hashed passwords, JWT bearer tokens (`JWT_SECRET`, with `iat`).
  A password change refuses the account's tokens issued before it
  (`password_changed_at`, Unix seconds; Postgres `0008_password_changed_at.sql`)
  and returns a new token, which the web app saves; an unknown email
  still checks a dummy bcrypt hash (no timing hint). Covered by
  `tests/test_roles_auth.py`.
- **Manager types** (`backend/permissions.py`, `staff.manager_type`:
  SQLite `_ADDED_COLUMNS` + startup backfill, Postgres
  `0006_manager_types.sql` with CHECKs). Tech Lead (default; managers from
  before types), Product Manager and Incident Manager are peers with the
  department scope; a Platform Lead sees every department. One
  `PERMISSIONS` table (tickets / reassign / incidents: `department` or
  `all`; teams) decides; `manager_scope(conn, user, department_id)` gives
  the categories (None = every ticket) used by manager.py, staff_tickets,
  chats and incidents. The type is read in `auth._load_user` on every
  request, never from the token (a demoted Platform Lead loses it on the
  next request). Only the admin sets it (Users, setup wizard step
  Managers; audited with `previous_manager_type`); a role change sets or
  clears it; the admin account has none. Platform Lead: `department=<id>|all`
  on /api/manager/{dashboard,sla,tickets,technicians} (403 for anyone
  else), `/api/manager/teams`, every incident, reassign to any active
  support engineer (the ticket stays with its category's department;
  `ticket.reassigned_across_departments` audit with from/to user and
  department). Incident Manager = Tech Lead for now; widening its
  incidents is `"incidents": ALL` in the table. Frontend:
  `lib/managerScope.js` (`?department=`), `components/manager/`
  (DepartmentPicker, Teams), nav items with `needs` (from /auth/me's
  `permissions`). Covered by `tests/test_manager_types.py`.
- **Ticket lifecycle + support engineer workspace** (reconcile sub-stage B;
  `backend/staff_tickets.py`, `backend/ticket_lifecycle.py`,
  `frontend/src/components/StaffTicketView.jsx`). Statuses
  `db.TICKET_STATUSES`: Open (with the support team, owner optional), In
  Progress, Pending Customer, Resolved, Closed. Every status/owner change
  goes through `ticket_lifecycle.set_status` / `set_assignee` /
  `record_assignment`, which write `ticket_status_history` /
  `ticket_assignment_history` (actor = user id, or `system` for the AI
  pipeline). **Claim** (`POST /api/staff/tickets/{id}/claim`):
  `BEGIN IMMEDIATE` + `UPDATE ... WHERE assigned_technician_id IS NULL`,
  so of two simultaneous claims one gets 409. Only the owner replies
  publicly or changes status; any support engineer adds internal notes;
  managers see their department only and reassign / set priority there
  (`/api/manager/tickets/{id}/{reassign,priority}`, logged).
  **Message visibility** (`ticket_messages.visibility`): `public_reply`,
  `internal_note`, `system_event` (+ `customer_visible`). Customer
  endpoints filter with `db.CUSTOMER_VISIBLE_SQL` in the query, and the
  AI transcript (`main._transcript_for`) only ever includes public
  replies. Customer reply on Pending Customer / Resolved -> Open (owner
  kept). AI-handled tickets (route ai/clarify) stay out of the workspace.
  Covered by `tests/test_ticket_workspace.py`.
- **Rate limiting + production secrets** (`backend/rate_limit.py`,
  `auth.check_production_config`, `db_postgres.production_problems`):
  `/api/auth/login` is limited per client IP (every attempt) and per
  account (failures only; success clears them), 429 + Retry-After, checked
  before the password; sign-up per IP (`check_signup`, 5/hour), or closed
  altogether with `CUSTOMER_SIGNUP_ENABLED=false` (403; `/api/meta`
  `signup_open` hides the web links; the pilot runs with it off); every AI
  endpoint (start chat, chat message, new ticket, ticket reply) through
  `auth.get_ai_customer` -> `check_ai_turn`: 20 turns / 10 min and 200 /
  day per customer, 60 / 600 per IP, refused before the model runs. Caps:
  ticket description 8000, reply 4000, sign-up name 120 / email 254,
  passwords at most 72 bytes (bcrypt's limit; 400 on sign-up/change,
  `verify_password` compares the first 72 bytes so a long login never
  500s), and `conversation.latest_transcript` sends the model at most the
  latest 12,000 characters of a conversation. Env-configurable, in-memory
  per process; client IP from X-Forwarded-For only with
  `TRUSTED_PROXY_HOPS` (1 behind an ALB). Off in tests by default
  (`tests/conftest.py`; `tests/test_ai_limits.py` turns them on). In production startup
  refuses a placeholder/short JWT_SECRET, a weak ADMIN_PASSWORD, and on
  Postgres a weak/local-only DB password or no required SSL. Covered by
  `tests/test_rate_limit.py`, `tests/test_roles_auth.py`.
- **Container / AWS hosting** (`Dockerfile`, `.dockerignore`,
  `docs/AWS_DEPLOY.md`): python:3.13-slim, runtime requirements only,
  non-root, `/health` check; planned on ECS Express Mode (Fargate) + RDS +
  Amplify, not deployed (`AWS_PLAN.md`). `tests/test_dockerfile.py`.
  Sahayak pilot (`docs/SAHAYAK_PILOT_HOSTING.md`; nothing created yet):
  every name is `sahayak-*` (profile `sahayak`, cluster `sahayak`, VPC
  `sahayak-vpc`), and `aws_lib.guard_names` stops a script before its
  first call if the profile, a name or a found ARN says ticketapp (same
  account). `scripts/aws_up.sh` (idempotent; own VPC with 2 public subnets
  for the service and 2 private ones for the DB, no NAT; own cluster;
  attachments bucket; restores RDS from the newest `sahayak-db-*`
  snapshot, 7-day backups; task role may invoke Nova Lite and Pro;
  `CUSTOMER_SIGNUP_ENABLED=false`; stops if the load balancer is outside
  the VPC; rebuilds the Amplify frontend only when the API URL changed,
  runs `scripts/aws_smoke.py`), `scripts/aws_pause.sh` /
  `aws_resume.sh` between sessions (service to 0 tasks, falling back to
  the plain ECS count if Express refuses 0, and RDS stopped; same URL) and
  `scripts/aws_down.sh` at the end (typed "yes", snapshot first, then
  deletes the service and DB, keeps the newest `KEEP_SNAPSHOTS`). Without Docker, `scripts/aws_build_image.sh`
  builds the image in CodeBuild (clean git tree required, tag = short
  commit hash, exits early if ECR has it; x86_64 only, so `aws_up.sh`
  asks for ARM64 only when the manifest has an arm64 variant). Shared
  helpers (incl. `ensure_ecr_repo`) in `scripts/aws_lib.sh`; tested
  against a fake `aws` CLI (`tests/fake_aws_cli.py`,
  `tests/test_aws_scripts.py`) that rejects options the real subcommand
  doesn't accept (`tests/fake_aws_options.json`, generated from the CLI's
  help by `tests/aws_cli_options.py`).
- **Run locally**: `uvicorn backend.main:app --reload` (repo root, needs
  `.env`) + `npm run dev` in `frontend/` (proxies `/api` to `:8000`).
  The web demo: `scripts/webdemo.sh start|stop|status` (backend :8010
  with `.env`, frontend :5180; state in `.local/webdemo/`).
  SQLite uses the DELETE journal by default (`db._journal_mode`): WAL
  deadlocked every endpoint under concurrent requests with SQLite 3.51.0;
  `SQLITE_JOURNAL_MODE=WAL` opts back in.
- **Phase 2 (not yet done)**: swap SQLite → Azure SQL/Cosmos in
  `backend/db.py`, plain JWT → Azure AD B2C in `backend/auth.py`,
  `uvicorn --reload` → Azure App Service/Functions. No pipeline-logic
  changes expected.

## Status

**Done:** the AI help desk (`backend/` + `frontend/`): roles and auth, AI
chat sessions with resolution/escalation, email-style tickets with
attachments, support engineer workspace, modular validated AI service, AI
incident correlation with manager review, admin console. **Stage 1 of
Sahayak:** product-neutral core, categories and product profile as data,
KB and terms in the database (empty by default), neutral test fixture;
the suite is green on SQLite and on Postgres (`DB_BACKEND=postgres
TEST_DATABASE_URL=...`; locally `PG_LOCAL_PORT=5434 scripts/pg_local.sh
start`, as 5433 may be ticketapp-ai-aws's server).

**Ingester vertical slice** (`kb_ingester/`, see above): one URL to
reviewed entries, checked in a browser with the mock AI.

**Manager hierarchy** (see Manager types): Tech Lead / Product Manager /
Incident Manager peers and the Platform Lead, with Teams and the
department dropdown.

**Next:** a real run against Bedrock (needs the user's go-ahead on cost
and credentials), then crawl, sitemaps, forums, file upload, pasted text.
