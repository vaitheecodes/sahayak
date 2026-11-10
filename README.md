# Sahayak

An AI-powered help desk for any product, inspired by Zoho Desk and AI
customer-experience platforms such as Thunai.ai, Zendesk AI and Intercom
Fin. The product is configured, not coded: its name, categories and
knowledge base are data, and the knowledge base is built from the
product's own content (`kb_ingester/`; one URL at a time so far).

- **Customers** chat with an AI assistant grounded in the product's
  knowledge base, or raise email-style tickets with attachments.
- **The AI** answers what it can, asks one targeted question when unsure,
  and hands everything else to people with a summary and suggested next
  steps, so nobody has to repeat themselves.
- **Support engineers** claim tickets from an unassigned queue, reply to the
  customer, and keep private internal notes.
- **Managers** review AI-detected *incidents* (several customers reporting
  what may be one problem) for their department, and oversee workload.
- **The admin** manages accounts, departments, AI routing settings and
  reads the audit log.

Sahayak started as a copy of ticketapp-ai-aws (a help desk for one
monitoring product); the product-specific data, its pipeline and its
wording were removed so it starts with an empty knowledge base.

## Contents

- [Architecture](#architecture)
- [Setup and startup](#setup-and-startup)
- [Environment variables](#environment-variables)
- [Database and migrations](#database-and-migrations)
- [AI configuration](#ai-configuration)
- [Roles and workflows](#roles-and-workflows)
- [API](#api)
- [Testing](#testing)
- [Features: completed and tested](#features-completed-and-tested)
- [Known limitations](#known-limitations)
- [Knowledge base](#knowledge-base)

## Architecture

```
React (Vite) — frontend/            one login page; portals per role:
  /customer  /technician  /manager  /admin
        │  fetch /api/*  (JWT bearer)
        ▼
FastAPI — backend/
  main.py            auth, customer tickets, attachments, /meta
  chats.py           AI chat sessions (separate from tickets)
  staff_tickets.py   support engineer workspace, manager overview
  incidents.py       AI incident correlation + manager review
  admin.py           accounts, departments, settings, audit log
  ticket_lifecycle.py / audit.py / app_settings.py
        │
        ├── graph.py        LangGraph routing pipeline
        │     retrieve KB → classify → decide route
        │       → answer | ask a clarifying question | hand to a human
        ├── ai_service/     every model call: one module per operation,
        │                   pydantic-validated input/output (Azure OpenAI)
        └── kb_retrieval.py TF-IDF retrieval over the 386 KB entries
        ▼
SQLite (DB_PATH) + uploads/ next to it
```

Stack: Python 3.10, FastAPI, LangGraph, Azure OpenAI (`openai`
package), SQLite, bcrypt + JWT · React 19, Vite, React Router · pytest.

## Setup and startup

Prerequisites: Python 3.10, Node 20+, an Azure OpenAI chat deployment.

```bash
pip install -r requirements.txt
```

```bash
cp .env.example .env
```

Fill in at least the `AZURE_OPENAI_*` values and `JWT_SECRET` (see
[Environment variables](#environment-variables)). Then run the backend
from the repo root:

```bash
uvicorn backend.main:app --reload
```

and the frontend in a second terminal:

```bash
cd frontend && npm install && npm run dev
```

Open http://localhost:5173. Vite proxies `/api` to `:8000`.

On first start the backend creates the database, seeds eight neutral
categories (ACCOUNT, BILLING, DATA, SETUP, USAGE, ISSUE, INTEGRATION,
OTHER) and three default departments covering them, and creates the admin
account:

- **Admin**: from `ADMIN_EMAIL` / `ADMIN_PASSWORD`. If they're unset in
  development, a fallback admin is created and a warning with the details
  is logged (`backend/auth.py`). In production (`APP_ENV=production`) the
  server refuses to start without them.
- **Demo staff** (development only, never in production): a manager
  (Product Support department) and a support engineer; credentials in
  `backend/seed_data.py`.
- **Customers** sign up on the login page (or the admin creates them).

The knowledge base starts empty: until entries are approved, every
question gets the "I don't have a guide for that yet" hand-off to a
ticket. See [Knowledge base](#knowledge-base). Name the product in
**Settings → Product** (admin); until then the AI says "the product".

**Deployment (Azure).** The backend runs on App Service (`Procfile`,
`runtime.txt`); set the variables below as Application Settings, with
`DB_PATH=/home/data/ticketapp.db` so the database and uploads persist,
`APP_ENV=production`, `ADMIN_*`, and `ALLOWED_ORIGINS` set to the frontend
origin. The frontend builds to Static Web Apps with
`VITE_API_URL=https://<app>.azurewebsites.net/api` set at build time
(`frontend/.env.example`).

**Continuous deployment.** Two GitHub Actions workflows deploy on push to
`main`: `.github/workflows/deploy-backend.yml` (changes under `backend/`,
`requirements.txt`, `runtime.txt`; packages committed files
with `git archive` and deploys to the `ticketapp-ai-api` App Service) and
`.github/workflows/deploy-frontend.yml` (changes under `frontend/`; builds
with Node 22 and deploys `frontend/dist` to the Static Web App). Both can
also be run manually (Actions → workflow → Run workflow). They need two
repository secrets: `AZURE_WEBAPP_PUBLISH_PROFILE` (App Service → Download
publish profile; requires SCM Basic Auth Publishing Credentials to be on)
and `AZURE_STATIC_WEB_APPS_API_TOKEN` (Static Web App → Manage deployment
token).

## Environment variables

All are documented in `.env.example`. Never commit real values.

For Catalyst AppSail (Phase 4), the required console variables, build and
deploy steps are in [docs/appsail-deploy.md](docs/appsail-deploy.md).

| Variable | Default | Purpose |
|---|---|---|
| `AI_PROVIDER` | `azure` if `AZURE_OPENAI_ENDPOINT` is set, else `mock` | `quickml_appsail`, `bedrock`, `openai_compatible`, `azure`, `mock` (see `backend/ai_service/backends.py`) |
| `AI_MAX_TOKENS`, `AI_TIMEOUT_SECONDS` | 2048, 90 | Per-call limits |
| `QUICKML_ENDPOINT_KEY`, `QUICKML_ENDPOINT_NAME`, `QUICKML_ORG_ID` | — | Catalyst QuickML LLM Serving endpoint, called from AppSail with the credential AppSail injects per request ([docs/quickml-appsail-call.md](docs/quickml-appsail-call.md)) |
| `QUICKML_ENVIRONMENT`, `QUICKML_API_BASE` | `Development`, `https://api.catalyst.zoho.in` | Fallbacks when AppSail doesn't inject `X-ZC-Environment` / `X_ZOHO_CATALYST_CONSOLE_URL` |
| `BEDROCK_MODEL_ID_CHAT` | — (uses `BEDROCK_MODEL_ID`) | Optional model for the customer-facing chat answer only; every other AI call keeps `BEDROCK_MODEL_ID` |
| `BEDROCK_MODEL_ID`, `AWS_REGION` | `apac.amazon.nova-lite-v1:0`, `ap-south-1` | `bedrock` provider (Converse API); credentials from the default AWS chain only (`AWS_PROFILE` locally, the IAM role when deployed) |
| `AI_BASE_URL`, `AI_API_KEY`, `AI_MODEL`, `AI_EMBEDDING_MODEL` | — | `openai_compatible` provider |
| `AZURE_OPENAI_ENDPOINT`, `AZURE_OPENAI_API_KEY`, `AZURE_OPENAI_API_VERSION`, `AZURE_OPENAI_DEPLOYMENT` | — | `azure` provider (removed in Phase 4 C6) |
| `AZURE_OPENAI_EMBEDDING_DEPLOYMENT` | unset | Optional embeddings with `azure`; otherwise incident grouping uses lexical TF-IDF similarity |
| `JWT_SECRET` | dev value | Signs session tokens; use a long random value in production |
| `APP_ENV` | `development` | `production` requires `ADMIN_*` and skips demo staff |
| `ADMIN_EMAIL`, `ADMIN_PASSWORD` | — | The single admin, created once if no admin exists (never overwritten) |
| `DB_BACKEND` | `sqlite` | `sqlite` or `postgres` (see Database and migrations) |
| `DB_PATH` | `backend/ticketapp.db` | SQLite file; local attachments go to `uploads/` beside it |
| `STORAGE_BACKEND` | `local` | Attachment bytes: `local` (disk) or `s3` |
| `S3_BUCKET`, `S3_PREFIX` | —, `attachments/` | Private bucket and key prefix for `STORAGE_BACKEND=s3`; credentials from the default AWS chain only |
| `DATABASE_URL`, or `DB_HOST` `DB_PORT` `DB_NAME` `DB_USER` `DB_PASSWORD` `DB_SSLMODE` | — | Postgres connection (never logged; only host:port/db appears in logs) |
| `DB_POOL_MAX`, `DB_POOL_MIN`, `DB_POOL_TIMEOUT` | 10, 1, 10 s | Postgres pool size and how long a request waits for a connection before a 503 |
| `ALLOWED_ORIGINS` | localhost dev ports | CORS origins, comma-separated |
| `KB_MIN_SCORE` | 0.35 | A knowledge-base match below this score is no match: the AI asks one question or offers a ticket instead of answering (see `docs/KB_ENTRY_TEMPLATE.md`) |
| `INCIDENT_WINDOW_HOURS` | 12 | Reports considered together |
| `INCIDENT_MIN_TICKETS` | 3 | Group size before asking the AI (from 2+ customers) |
| `INCIDENT_SIMILARITY` | 0.15 | Similarity bar for splitting candidate groups (lexical TF-IDF; ~0.80 with embeddings) |
| `INCIDENT_ROUTING_CONFIDENCE` | 0.6 | Below this, an incident is "Needs routing" |
| `INCIDENT_MEMORY_DAYS` | 90 | How long resolved incidents are used to answer "was there an outage?" |
| `EMAIL_ENABLED` | `false` | Real email is off by default; the email-style thread is in-app |
| `SMTP_HOST`, `SMTP_PORT`, `SMTP_USERNAME`, `SMTP_PASSWORD`, `SMTP_FROM`, `SMTP_USE_TLS` | — | Used only when `EMAIL_ENABLED=true` |
| `VITE_API_URL` (frontend) | `/api` | API base for production builds |

The `INCIDENT_*` values are starting points: the admin can override them
(and the AI routing policy, and status labels) in **Admin → Settings**;
saved values win.

## Database and migrations

`DB_BACKEND` picks the database; both take the same SQL.

**SQLite** (default; local runs and the test suite): created and migrated
by `db.init_db()` on every startup — no separate migration step.
Migrations are in place and non-destructive (columns added, data moved,
never dropped), and safe to run repeatedly:

- legacy `agents` → `staff` (support engineers), `assigned_agent_id` →
  `assigned_technician_id`
- legacy statuses `awaiting_reply` → `pending_customer`, `assigned` →
  `in_progress`
- pre-session chat tickets → `chat_sessions` / `chat_messages` (escalated
  ones stay tickets, linked to the chat)
- legacy system messages → customer-visible system events
- manager → department many-to-many → one department per manager (first
  mapping kept)

Main tables: `customers`, `staff`, `admins`, `departments`, `tickets`,
`ticket_messages` (with `visibility`), `attachments`,
`ticket_status_history`, `ticket_assignment_history`, `chat_sessions`,
`chat_messages`, `chat_reviews`, `incident_clusters`, `incident_tickets`,
`incident_departments`, `incident_reviews`, `incident_deliveries`,
`incident_memory`, `audit_events`,
`app_settings`. Schema and comments: `backend/db.py`.

**PostgreSQL** (`DB_BACKEND=postgres`, for RDS): `backend/db_postgres.py`.
- Schema as versioned files in `migrations/postgres/` (`0001_initial.sql`
  matches the SQLite schema above), applied at startup or ahead of a
  deploy with `scripts/db_migrate.py [--status]`, under an advisory lock
  so several instances can start at once. Adds CHECKs on status columns
  and case-insensitive unique emails and department names (the app
  already enforced both). The SQLite legacy migrations aren't needed: a
  new database has no old rows.
- The existing SQL runs unchanged: placeholders are translated, rows act
  like `sqlite3.Row`, timestamps come back as the same ISO-8601 UTC
  strings, flags stay 0/1, JSON stays text.
- Connection pool with an explicit size and wait timeout; a full pool or
  an unreachable database answers **503** (`Retry-After: 2`) instead of
  hanging. No request holds a connection while the AI works (1-10 s):
  chat turns, ticket follow-ups and escalations read and commit, call the
  model, then re-check and write.
- Ticket claim (`repositories/tickets.py`): `UPDATE ... WHERE
  assigned_technician_id IS NULL ... RETURNING`; of concurrent claims
  exactly one wins. Writers that used SQLite's `BEGIN IMMEDIATE` take a
  transaction-scoped advisory lock.

Local Postgres for the tests (Homebrew, no Docker; data in `.local/`):

```bash
scripts/pg_local.sh start
```

```bash
DB_BACKEND=postgres TEST_DATABASE_URL=postgresql://ticketapp:ticketapp-local-test-only@127.0.0.1:5433/ticketapp_test pytest
```

The password exists only for that loopback test server.
`docker-compose.yml` is the same setup for Docker (unverified).

## Attachments

Customers attach up to 5 files per message (10 MB each; PNG, JPG, PDF,
TXT, LOG, with the contents checked against the extension). The database
keeps only metadata and a random `stored_name`; the bytes go to
`backend/storage.py`:

- `STORAGE_BACKEND=local` (default): `<DB_PATH parent>/uploads`.
- `STORAGE_BACKEND=s3`: a private bucket (`S3_BUCKET`, objects under
  `S3_PREFIX`, server-side encrypted), with credentials from the default
  AWS chain (`AWS_PROFILE` locally, the IAM role when deployed).

Downloads are only through `GET /api/tickets/{id}/attachments/{id}`: the
customer of that ticket (only from messages they can see), staff or the
admin. The app checks access, then streams the bytes itself; no public or
presigned URL is ever created. `scripts/s3_storage_check.py --yes` does a
real put/get/delete round trip against the bucket.

## AI configuration

Every model call goes through `backend/ai_service/` (one module per
operation: categorize, chat answer / clarify / follow-up check,
conversation and ticket summaries, suggested steps, incident correlation
incident summary, post-incident summary draft, incident-question parsing):

- **Validated output**: each operation has a pydantic schema; output is
  checked (plus semantic checks, e.g. correlated ticket ids must be from
  the input) and retried once, then the caller treats the AI as
  unavailable.
- **Transient Bedrock errors**: throttling and timeouts get one retry after
  about 1 s plus jitter; access, validation and configuration errors are
  never retried.
- **AI failures never change state**: a chat or ticket is never resolved,
  closed or escalated because a call failed; the customer's message is
  kept, and raising a ticket always works.
- **Prompt-injection defence**: instructions in the system message,
  customer text in delimited data blocks the customer can't close, and the
  model is told to treat them as data. Internal notes never reach a
  prompt; incident analysis sees customers only as anonymous labels.
- **Grounding**: answers and suggested steps use the closest KB entries;
  prompts forbid inventing results or claiming to have checked systems
  the app isn't connected to.
- **Amazon Bedrock** (`AI_PROVIDER=bedrock`): the Converse API through
  boto3, with the AWS credentials from the default chain (never in code or
  `.env`). Structured (JSON) operations use Converse tool use: the
  operation's schema is a tool the model is forced to call, because Nova
  Lite asked for JSON in text echoed the schema instead of filling it. boto3's own retries are off, so a throttled or failed call is
  reported once, like every provider. Access denied, an unknown model id
  and invalid requests are logged as configuration errors; the AWS error
  text is never logged. `scripts/bedrock_quality_check.py` runs the 10 key
  prompts against the real model (billed) and reports rejected replies,
  latency, tokens and an estimated cost.
- **Routing policy** (`graph.decide_route`, editable in Admin →
  Settings): escalation language (abuse, negation, long compound
  messages) → human; high-risk categories (ACCOUNT, BILLING, DATA) below 90%
  confidence → an `escalate_with_info` KB entry's steps and collect
  list, then a ticket; a vague first report gets one clarifying
  question, then a human; otherwise human; a how-to ("how do I add X?")
  is answered from the KB, or told there's no guide yet and handed to a
  human, never asked "are you referring to...?" (one fixed question
  first only when it names nothing to do, or when the guides are for
  one platform each, e.g. Android / iOS, and it names neither); other categories
  below 75% → up to 3 clarifying questions, then human; otherwise the AI
  answers.
- **Answers stay grounded** (`backend/request_kind.py`,
  `ai_service/grounding.py`): steps the matched KB entry doesn't support
  (menu paths, hostnames, ports, numbers) are dropped from answers and
  from the support engineer's suggested steps ("No KB match - needs triage"
  when nothing matches); the exact error message is asked for only after
  the customer reported an error.

## Roles and workflows

| Role | Signs in at | Can |
|---|---|---|
| Customer | `/login` → `/customer` | chat with the AI, raise tickets with attachments, follow up, reopen, see chat history |
| Support engineer | → `/technician` | dashboard of their own tickets (counts by status for the period, the matching list, charts), tickets (unassigned / mine / all open / recently resolved, filters), read-only chats, claim, reply, internal notes, status, AI hand-off panel, chat reviews, incidents assigned to them (resolve & send summary), Try a ticket (`/try-a-ticket`) |
| Manager (one department) | → `/manager` | incidents for their department (confirm / investigate / dismiss, correct departments, assign a support engineer, resolve & send the post-incident summary), dashboard and SLA for their department, department tickets (reassign to the department's support engineers, priority), chats, chat reviews, Try a ticket (`/try-a-ticket`) |
| Anyone | `/incidents`, `/docs` | public incident history and the read-only docs (routing policy, ticket statuses), no login |
| Admin (single account) | → `/admin` | SLA targets (in Settings), users (customers, support engineers, managers: create, edit, deactivate, reset password), departments, settings, activity/audit log. No access to tickets, dashboards, SLA reports, chats, chat reviews, incidents or Try a ticket (403) |

After upgrading, the admin must give each support engineer a department under Users, or a manager's reassign list stays empty.

**Chat.** A chat is not a ticket. If the customer confirms it's solved, it
closes with an AI summary and an internal review record (no ticket). If it
needs a person — the customer asks, the AI can't do it, the routing
policy says so, or the customer clicks *Raise a ticket* — an unassigned
Open ticket is created with the transcript linked, an AI summary and
suggested next steps; the customer gets the ticket number.

**Tickets.** Statuses: Open, In Progress, Pending Customer, Resolved,
Closed (labels configurable). Claiming is atomic (two simultaneous claims:
one wins, one gets 409). Every status and owner change is recorded in
history and the audit log. Customer replies return Pending Customer and
Resolved tickets to Open.

**Incidents.** After each new ticket or escalation, recent tickets from
the same component area and at least two customers are sent to the AI,
which decides whether they share an incident, separating observed facts
from hypotheses. Clusters are reused for an ongoing event, routed to the
owning department only when the AI is confident enough, and never close
or merge tickets. Once a manager confirms one, affected customers see a
neutral "we're aware of this issue" notice.

**Resolving an incident.** Only a confirmed incident can be resolved, by
a manager or the support engineer it's assigned to: they enter what was done,
when the fix was applied (IST) and, optionally, the root cause. The AI
drafts a customer summary (what happened, what was fixed, what to do) and
an internal one from the incident's facts and that note only; code adds
the start–resolution times and the cause line (the staff-entered cause,
or "still being reviewed"), and a check rejects any model text with a
time, date or cause claim. Staff edit, preview and *Approve & send* —
never automatic. The summary is posted on every linked ticket as a public
reply from the Support Team (and emailed when `EMAIL_ENABLED=true`), with
a delivery record per ticket: sending twice never duplicates, a failing
ticket doesn't block the others and can be retried. Linked tickets are
marked Resolved only if staff tick the box.

**"Was there an outage?"** Confirmed and resolved incidents are kept in
`incident_memory` (category, times, approved summary, affected customer
ids, visibility, optional embedding) for `INCIDENT_MEMORY_DAYS`. In a
chat or an AI-handled ticket, a message that looks like a question about
an outage (keyword gate, then the AI turns it into an absolute IST time
window and topic) is answered from that memory with fixed templates: an
affected customer hears "Yes — you reported this on … (ticket …)" and the
approved summary; anyone else hears about it only if staff made it
public; otherwise "no known incident matched" and an offer to raise a
ticket. Unresolved incidents are described as being investigated, with no
cause. The model never writes the answer, so it can't invent an incident
or reveal another customer's details.

## API

64 endpoints, grouped by role, with request and response formats:
**[docs/API.md](docs/API.md)**. A running server also serves Swagger at
`/docs`.

## Testing

```bash
pytest tests/
```

```bash
cd frontend && npm run build && npm run lint
```

By default the suite runs on SQLite. With `DB_BACKEND=postgres` and
`TEST_DATABASE_URL` (a database whose name ends in `_test`; every table
is truncated before each test) the same suite runs on Postgres; if that
database isn't reachable the tests are skipped with the reason.
`TEST_DB_POOL_MAX=1` makes a Postgres run fail on any code that holds a
connection while asking for another.

The pytest suite covers the help desk; tests never
call the real AI provider (`tests/conftest.py` disables it; individual
tests script the model's replies). Highlights:

| File | Covers |
|---|---|
| `test_e2e_helpdesk.py` | the full journey: chat → escalation → support engineer claim, reply + private note → customer view → correlated incident → manager confirms (real pipeline, scripted model) |
| `test_roles_auth.py` | admin bootstrap, roles, login routing, forced password change, departments |
| `test_chat_sessions.py`, `test_chat_followup_gates.py`, `test_handoff_escalation.py` | chat resolution vs escalation, AI-failure handling, review records, migration |
| `test_ticket_workspace.py` | claim race, public vs internal visibility, history, manager scope |
| `test_ai_service.py` | schema validation and retry, provider failure, injection containment, no secrets in logs |
| `test_storage_s3.py` | S3 attachments with a fake client: only metadata in the DB, validation before any upload, cleanup on failure, downloads only through the authorised endpoint (no links), S3 errors → 503 without AWS text, bad settings stop startup |
| `test_postgres_backend.py` | SQL translation, rows, settings never leak the password, 20 concurrent claims with exactly one winner (SQLite and Postgres), more chat turns than pool connections without deadlock, exhausted pool answers 503 |
| `test_ai_providers.py`, `test_bedrock_provider.py` | each provider's request, response parsing, retry note, error mapping (only throttling/timeouts retried, once; nothing secret logged), AI failure changes nothing; boto3 is always faked |
| `test_kb_retrieval.py`, `test_kb_store.py`, `test_topic_terms.py` | KB retrieval (one topic per entry, `KB_MIN_SCORE` floor, only the customer's own words searched, drafts never searched); the database KB on SQLite and Postgres: packs, validation, terms |
| `test_product_neutral.py` | categories as data, the product profile in prompts, and no product-specific words in code, prompts, migrations or frontend |
| `test_incidents.py` | clustering, time window, pre-filters, dedupe, routing, review, banner |
| `test_incident_resolution.py` | resolve only when confirmed, facts-only draft (invented times/causes rejected), idempotent fan-out, per-ticket failure isolation, email gate, "was there an outage?" answers (linked / unlinked / public / expired, no cross-customer leakage), AI failure sends nothing |
| `test_admin_console.py` | account administration, settings, audit log, email gate, attachment access |
| `test_customer_tickets.py` | ticket model, email-style replies, attachments |

The frontend has no automated tests; it was verified by building, linting
and clicking through each portal in a browser at desktop and phone widths.

## Features: completed and tested

- Single login with role routing; customer signup; one env-configured
  admin; admin-created staff and customers with forced password change;
  deactivation that blocks live sessions.
- AI chat with KB grounding, clarifying questions, follow-up handling,
  resolution summaries + internal review, escalation to an unassigned
  ticket with summary, suggested steps and linked transcript.
- Email-style tickets with attachments (validated, private storage,
  authorised download), replies, reopen, unread markers.
- Support engineer workspace: queues, search/filters, atomic claim, public
  replies vs private notes (filtered in SQL for customers), status
  changes, history, AI hand-off panel.
- Manager department oversight and workload; AI incident correlation
  with confidence, facts vs hypotheses, department routing, Needs
  routing, review with notes, customer notice on confirmed incidents.
- Post-incident summaries (AI draft, staff edit, approve & send to every
  linked ticket, idempotent with per-ticket delivery status), incident
  memory answering "was there an outage?", public incident history page.
- Admin console: ticket dashboard (status, priority, per-day volume, open
  work by support engineer, first-response and resolution times), users with
  one-time temporary passwords, optional SLA per priority (24x7 clock,
  paused while waiting on the customer, compliance and at-risk lists, SLA
  shown on staff ticket cards), departments, settings, incidents, audit log.
- Light and dark themes (follows the OS, or forced from the header);
  design tokens and contrast checks in `docs/DESIGN_SYSTEM.md`.
- Modular, validated AI service; graceful AI failure everywhere.

## Known limitations

- **One process.** Settings are cached per process, and incident
  correlation runs as an in-process background task. Postgres removes the
  single-file limit, but several workers would each keep their own
  settings cache until it's refreshed.
- **Attachments on S3 are read into memory** to stream them (fine at the
  10 MB limit). No lifecycle rule or virus scan yet.
- **The negation rule is broad.** Any "no"/"not" sends a message to a
  person, so most long ticket descriptions skip the AI. Admins can turn
  it off in Settings.
- **Chats are never marked abandoned automatically;** an idle chat stays
  active and can be resumed.
- **Incident correlation looks at tickets only** (not AI-resolved chats).
  Without an embeddings deployment, grouping is by department/category,
  and the AI does the fine-grained judgement.
- **The ticket form has no separate contact email/phone or product
  fields;** the account's name and email and the category are used.
- **Composer formatting** is a Markdown subset (bold, code, lists), not a
  WYSIWYG editor. Only customers can attach files.
- **No "reply to all linked tickets"** (optional in the spec).
- **"Take this chat"** (joining a live AI chat) is a placeholder.
- **Real email is send-only and off by default;** there's no inbound
  email.
- **Session tokens** live in `localStorage` with no refresh tokens. Failed
  logins are audited but not rate-limited.
- **Legacy data:** admin accounts created by the old public admin signup
  are kept (a warning is logged); remove extras manually.

## Knowledge base

The knowledge base lives in the database (`backend/kb_store.py`,
tables in `backend/db.py` and `migrations/postgres/0003_kb.sql`):

- **Entries** (`kb_entries`): a title, an answer, numbered steps (each
  with the passage of the source it is backed by), several customer-style
  questions, a kind (how-to / troubleshooting), a category, the product
  terms it applies to, and the source URL. Status draft / approved /
  rejected / retired; only approved entries are searched.
- **Terms** (`kb_terms`): the product's modules, variants, platforms,
  integrations and editions with their aliases, learned from its content
  and confirmed by a reviewer. An entry for one of them grounds a reply
  only when the customer has mentioned it.
- **Categories** (`kb_categories`): neutral defaults, extended without code.
- **Sources, runs, documents, chunks**: where content came from and how
  it was ingested (`kb_ingester/`, below).

### Building it from a product's pages

Managers and support engineers find it under **Knowledge base** in the
sidebar (the admin doesn't review the KB).

1. **Sources** (manager): add a public page URL, upload a TXT, Markdown
   or PDF file (up to 10 MB), or paste text (up to 200,000 characters),
   and tick the confirmation that the content is public or allowed to be
   used (your name and the time are stored). Private and internal
   addresses are refused. A scanned PDF (no text) is reported as such:
   there is no OCR yet. File and text content isn't kept, so to run one
   again, upload or paste a new version.
2. **Estimate a run** (manager): the page is fetched and split into
   sections, with no model calls, and the cost is shown: pages x sections
   x 2 model calls (one to draft, one to check the steps). Unchanged pages
   and sections cost nothing. **Start run** drafts them; a run stops
   cleanly at the per-run or per-day cap (admin Settings -> Knowledge base
   limits) and the next run continues.
3. **Review queue**: drafts with their flags (possible duplicate, source
   changed, suspicious text, answer removed). The editor shows each step
   beside the passage it is quoted from. Support engineers edit; managers
   approve or reject. Only approved entries are used by the bot.
4. **Terms / Categories**: the drafter proposes product terms and
   categories; support engineers can propose terms too; managers confirm,
   reject or merge them.

Every step of a draft must quote a passage of its page, and a second
model call checks the passage supports it; the answer must be in the
model's own words. A numbered list on the page is read by code and
rewritten one step per item; an entry that ends up with fewer steps than
its list is marked "possibly incomplete (X of N)" and needs an explicit
confirmation to approve. A source can carry a licence note (for example
CC BY-SA 4.0), kept on its entries with the source link. The drafting
model can be changed per operation (admin Settings -> AI models), and
`scripts/kb_eval.py` measures drafting quality on saved pages. Pages are never stored: only a hash, the section text
until its drafts are decided (30 days at most), and the short quotes.

A reviewed KB moves between environments as a JSON pack (format: the
neutral test fixture `tests/fixtures/kb/brightdesk.json`, a fictional HR
product):

```bash
.venv/bin/python scripts/kb_import.py PACK.json
```

```bash
.venv/bin/python scripts/kb_import.py --export OUT.json
```

Import asks for a typed "yes", imports everything as approved, and writes
nothing if any entry is invalid.
