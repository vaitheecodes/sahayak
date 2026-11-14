# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users
Four roles share one help desk for any product (configured per client:
its name, categories and knowledge base are data):

- **Customers** ask the AI support chat first, raise email-style tickets,
  and follow their tickets.
- **Technicians** work the queue all day: claim, reply, add internal notes,
  review AI-resolved chats.
- **Managers** oversee their department's tickets and workload, review AI
  incident clusters, review chats.
- **The admin** runs the dashboard, all tickets, SLA targets, users and
  departments.

Confirmed: the UI must suit daily, long-session use (density, speed,
scanability) and also demo well to portfolio reviewers clicking through
every screen.

## Product Purpose
Answer customers from the knowledge base with an AI chat, hand the rest to
people with a useful brief, spot outages across tickets, and keep response
and resolution within SLA. Success: fewer tickets reach a human, and the
ones that do are resolved within their SLA.

## Positioning
The AI is grounded only in the approved KB answers and a routing policy
with stricter bars for high-risk categories (account, billing and data);
it asks one clarifying question or hands off with a brief
rather than guessing. Incidents are correlated across customers by AI and
confirmed by a manager.

## Operating Context
Portfolio project for AWS data/AI engineering roles. React (Vite) frontend,
FastAPI backend, SQLite locally and Postgres on AWS. Routes per role:
/customer, /technician, /manager, /admin; public /docs, /incidents.

## Capabilities and Constraints
- Ticket statuses: Open, In Progress, Pending Customer, Resolved, Closed
  (display labels set by the admin).
- Priorities low / medium / high / urgent; SLA first-response and
  resolution targets per priority.
- The chat bot is a friendly named helper, "Pip", always shown with an "AI assistant" badge (one constant: `frontend/src/lib/people.js` `BOT_NAME`).
- Routing policy is public and read-only at /docs.

## Brand Commitments
- Product name in the UI: "Help Desk"; the chat bot is "Pip" ("Pip answers from
  our approved help articles"). The backend's own sender name is unchanged. No
  third-party brand name appears in the UI, and no invented brand name
  replaces it.
- Not a copy of any brand's look.

## Evidence on Hand
KB content comes from the client's own public material (the ingester);
the tests use a fictional product, Brightdesk HR. No real customers,
testimonials or usage numbers: demo data only, never presented as real.

## Product Principles
- The task comes first: queues, tickets and SLA state readable at a glance.
- Honest data: zeros as zeros, missing as a dash, no invented figures.
- The AI is transparent: who answered (bot or person) is always visible.
- Same access rules in UI and API: a page hidden from a role is a 403 too.

## Accessibility & Inclusion
WCAG AA contrast in light and dark, visible focus rings, labels on every
field, keyboard-operable navigation and menus.
