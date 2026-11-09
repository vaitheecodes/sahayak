"""Ticket and SLA reporting, shared by the manager and technician dashboards.

The admin console no longer has reports (people and system only); the
same aggregation now serves:

  manager      dashboard_data / sla_data with the department's categories
               (backend/manager.py: /api/manager/dashboard, /api/manager/sla)
  technician   technician_data for one technician's own tickets
               (backend/staff_tickets.py: /api/staff/dashboard)

A scope is a set of categories (a ticket belongs to the department that
owns COALESCE(category, requested_category)); None means every ticket and
an empty set none. Periods are fixed presets in IST (backend/periods.py).
Numbers are aggregated in Python from plain queries, so the same code runs
on SQLite and Postgres (timestamps come back as ISO text from both).
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime

from backend import app_settings, db, sla
from backend import ticket_lifecycle as lifecycle
from backend.conversation import subject_for
from backend.periods import Period, ist_day

STATUSES = ("open", "in_progress", "pending_customer", "resolved", "closed")
_COLUMNS = ("t.ticket_id, t.subject, t.ticket_text, t.route, t.ticket_type, t.assigned_technician_id, "
            "t.customer_id, s.name AS technician_name, "
            + ", ".join("t." + c.strip() for c in sla.SLA_COLUMNS.split(",")))


TICKET_CATEGORY = "COALESCE(t.category, t.requested_category)"


def scope_sql(categories: set[str] | frozenset | None, params: list, column: str = TICKET_CATEGORY) -> str:
    """The WHERE fragment for a category scope on `column` (appends its
    parameters)."""
    if categories is None:
        return "1 = 1"
    if not categories:
        return "1 = 0"
    params.extend(sorted(categories))
    return f"{column} IN ({', '.join('?' * len(categories))})"


def _rows(where: str, params: list, categories=None) -> list[dict]:
    params = list(params)
    clause = scope_sql(categories, params)
    conn = db.get_connection()
    try:
        return [dict(r) for r in conn.execute(
            f"SELECT {_COLUMNS} FROM tickets t LEFT JOIN staff s ON s.staff_id = t.assigned_technician_id "
            f"WHERE ({where}) AND {clause} ORDER BY t.created_at", params)]
    finally:
        conn.close()


def _between(column: str, period: Period) -> tuple[str, list]:
    return f"t.{column} >= ? AND t.{column} < ?", [sla.iso(period.start), sla.iso(period.end)]


def _minutes(start, end) -> float | None:
    a, b = sla.parse(start), sla.parse(end)
    return (b - a).total_seconds() / 60 if a and b and b >= a else None


def _avg(values: list[float]) -> float | None:
    return round(sum(values) / len(values), 1) if values else None


def _is_open(ticket: dict) -> bool:
    return ticket["status"] not in sla.DONE_STATUSES


def _per_day(values: list[datetime | None]) -> Counter:
    return Counter(ist_day(v) for v in values if v)


# ---------------------------------------------------------------------------
# Manager dashboard
# ---------------------------------------------------------------------------
def dashboard_data(period: Period, categories=None, technicians: list[dict] | None = None) -> dict:
    """KPIs now (open, in progress, unassigned, SLA at risk / breached),
    average first response for tickets created in the period, open tickets
    per technician and per priority, and tickets created vs resolved per
    IST day. `technicians` ({staff_id, name}) are listed even with nothing
    open."""
    where, params = _between("created_at", period)
    created = _rows(where, params, categories)
    where, params = _between("resolved_at", period)
    resolved = [t for t in _rows(where, params, categories) if not _is_open(t)]
    open_now = _rows("t.route = 'human' AND t.status NOT IN ('resolved', 'closed')", [], categories)

    settings = app_settings.get("sla")
    at = sla.now()
    states = [e["state"] for t in open_now if (e := sla.evaluate(t, at, settings))]
    first = [m for t in created if (m := _minutes(t["created_at"], t["first_response_at"])) is not None]

    workload = {t["staff_id"]: {"technician_id": t["staff_id"], "name": t["name"], "open": 0}
                for t in technicians or []}
    for t in open_now:
        key = t["assigned_technician_id"]
        if key is None:
            continue
        workload.setdefault(key, {"technician_id": key, "name": t["technician_name"] or key, "open": 0})
        workload[key]["open"] += 1

    made = _per_day([sla.parse(t["created_at"]) for t in created])
    done = _per_day([sla.parse(t["resolved_at"]) for t in resolved])
    last_day = ist_day(period.until())
    return {
        "period": period.as_dict(),
        "kpis": {
            "open": sum(1 for t in open_now if t["status"] == "open"),
            "in_progress": sum(1 for t in open_now if t["status"] == "in_progress"),
            "pending_customer": sum(1 for t in open_now if t["status"] == "pending_customer"),
            "unassigned": sum(1 for t in open_now if t["assigned_technician_id"] is None),
            "sla_at_risk": states.count("at_risk"),
            "sla_breached": states.count("breached"),
            "avg_first_response_minutes": _avg(first),
            "first_responses": len(first),
        },
        "created": len(created),
        "resolved": len(resolved),
        "technician_workload": sorted(workload.values(), key=lambda w: (-w["open"], w["name"].lower())),
        "open_by_priority": {p: sum(1 for t in open_now if t["priority"] == p) for p in sla.PRIORITIES},
        "over_time": [{"date": d.isoformat(), "created": made.get(d, 0), "resolved": done.get(d, 0)}
                      for d in period.days if d <= last_day],
    }


# ---------------------------------------------------------------------------
# SLA page
# ---------------------------------------------------------------------------
def _compliance(results: list[str]) -> dict:
    met, breached = results.count("met"), results.count("breached")
    decided = met + breached
    return {"met": met, "breached": breached, "percent": round(100 * met / decided, 1) if decided else None}


def sla_data(period: Period, categories=None, priority: str | None = None) -> dict:
    """Per priority for tickets created in the period: compliance (met /
    (met + breached), for each target), breached and at-risk counts; and
    every open ticket in scope at risk or past breach, soonest due first.
    Only tickets that got an SLA (created while it was on) count."""
    settings = app_settings.get("sla")
    at = sla.now()
    where, params = _between("created_at", period)
    if priority:
        where += " AND t.priority = ?"
        params.append(priority)
    evaluated = [(t, e) for t in _rows(where, params, categories) if (e := sla.evaluate(t, at, settings))]

    per_priority = {}
    for p in sla.PRIORITIES:
        rows = [e for t, e in evaluated if t["priority"] == p]
        per_priority[p] = {
            "tickets": len(rows),
            "first_response": _compliance([e["first_response"]["state"] for e in rows]),
            "resolution": _compliance([e["resolution"]["state"] for e in rows]),
            "breached": sum(1 for e in rows if not e["within_sla"]),
            "at_risk": sum(1 for e in rows if e["within_sla"] and e["state"] == "at_risk"),
            "within_sla": sum(1 for e in rows if e["within_sla"]),
        }

    def next_due(e: dict) -> str:
        running = [e[k]["due_at"] for k in ("first_response", "resolution")
                   if e[k]["state"] in ("at_risk", "breached") and not e[k]["done_at"]]
        return min(running) if running else e["resolution"]["due_at"]

    open_where = "t.status NOT IN ('resolved', 'closed')"
    open_params: list = []
    if priority:
        open_where += " AND t.priority = ?"
        open_params.append(priority)
    watch = sorted(
        ({"ticket_id": t["ticket_id"], "subject": subject_for(t), "priority": t["priority"], "status": t["status"],
          "technician_name": t["technician_name"], "created_at": t["created_at"], "next_due_at": next_due(e),
          "sla": e}
         for t in _rows(open_where, open_params, categories)
         if (e := sla.evaluate(t, at, settings)) and e["state"] in ("at_risk", "breached")),
        key=lambda r: sla.parse(r["next_due_at"]))
    return {
        "enabled": settings.enabled, "at_risk_percent": settings.at_risk_percent, "calendar": settings.calendar,
        "period": period.as_dict(), "priority": priority,
        "tickets_with_sla": len(evaluated),
        "by_priority": per_priority,
        "totals": {
            "within_sla": sum(1 for _, e in evaluated if e["within_sla"]),
            "breached": sum(1 for _, e in evaluated if not e["within_sla"]),
            "at_risk": sum(1 for _, e in evaluated if e["within_sla"] and e["state"] == "at_risk"),
        },
        "watchlist": watch[:200],
    }


# ---------------------------------------------------------------------------
# Technician dashboard
# ---------------------------------------------------------------------------
_ATTENTION_LIMIT = 10


def technician_data(period: Period, technician_id: str) -> dict:
    """One technician's own tickets only: cards (assigned, in progress,
    waiting on customer, resolved in the period, SLA at risk), the
    "needs my attention" list (SLA near breach first, then a new customer
    reply, then the rest by last update) and their numbers for the period."""
    settings = app_settings.get("sla")
    at = sla.now()
    mine = "t.route = 'human' AND t.assigned_technician_id = ?"
    open_rows = _rows(f"{mine} AND t.status NOT IN ('resolved', 'closed')", [technician_id])
    where, params = _between("resolved_at", period)
    resolved = [t for t in _rows(f"{mine} AND {where}", [technician_id, *params]) if not _is_open(t)]
    where, params = _between("first_response_at", period)
    responded = _rows(f"{mine} AND {where}", [technician_id, *params])

    conn = db.get_connection()
    try:
        latest: dict[str, dict] = {}
        if open_rows:
            ids = [t["ticket_id"] for t in open_rows]
            for m in conn.execute(
                    "SELECT ticket_id, sender, created_at FROM ticket_messages "
                    f"WHERE visibility = 'public_reply' AND ticket_id IN ({', '.join('?' * len(ids))}) "
                    "ORDER BY created_at", ids):
                latest[m["ticket_id"]] = {"sender": m["sender"], "at": m["created_at"]}
        reopened = conn.execute(
            "SELECT COUNT(*) FROM ticket_status_history h JOIN tickets t ON t.ticket_id = h.ticket_id "
            "WHERE t.assigned_technician_id = ? AND h.from_status IN ('resolved', 'closed') "
            "AND h.to_status NOT IN ('resolved', 'closed') AND h.changed_at >= ? AND h.changed_at < ?",
            (technician_id, sla.iso(period.start), sla.iso(period.end))).fetchone()[0]
        reviewed = conn.execute(
            "SELECT COUNT(*) FROM chat_reviews WHERE reviewed_by = ? AND reviewed_at >= ? AND reviewed_at < ?",
            (technician_id, sla.iso(period.start), sla.iso(period.end))).fetchone()[0]
    finally:
        conn.close()

    attention = []
    for t in open_rows:
        e = sla.evaluate(t, at, settings)
        last = latest.get(t["ticket_id"])
        near_breach = bool(e and e["state"] in ("at_risk", "breached"))
        customer_replied = bool(last and last["sender"] == "customer")
        updated = (last or {}).get("at") or t["created_at"]
        attention.append({
            "ticket_id": t["ticket_id"], "subject": subject_for(t), "priority": t["priority"],
            "status": t["status"], "ticket_type": t["ticket_type"], "sla": e, "updated_at": updated,
            "reason": "sla" if near_breach else ("customer_reply" if customer_replied else None),
        })
    order = {"sla": 0, "customer_reply": 1, None: 2}
    attention.sort(key=lambda r: (sla.parse(r["updated_at"]) or at).timestamp(), reverse=True)
    attention.sort(key=lambda r: (order[r["reason"]],
                                  # Near breach: breached first, then the least time left.
                                  (0 if r["sla"]["state"] == "breached" else 1,
                                   -(r["sla"]["resolution"]["used_ratio"] or 0)) if r["reason"] == "sla" else (0, 0)))

    first = [m for t in responded if (m := _minutes(t["created_at"], t["first_response_at"])) is not None]
    resolution = [m for t in resolved if (m := _minutes(t["created_at"], t["resolved_at"])) is not None]
    decided = [e["resolution"]["state"] for t in resolved if (e := sla.evaluate(t, at, settings))]
    open_states = [r["sla"]["state"] for r in attention if r["sla"]]
    return {
        "period": period.as_dict(),
        "cards": {
            "assigned": len(open_rows),
            "in_progress": sum(1 for t in open_rows if t["status"] == "in_progress"),
            "pending_customer": sum(1 for t in open_rows if t["status"] == "pending_customer"),
            "resolved": len(resolved),
            "sla_at_risk": open_states.count("at_risk") + open_states.count("breached"),
        },
        "attention": attention[:_ATTENTION_LIMIT],
        "attention_total": len(attention),
        "numbers": {
            "avg_first_response_minutes": _avg(first),
            "avg_resolution_minutes": _avg(resolution),
            "sla_met_percent": _compliance(decided)["percent"],
            "reopened": reopened,
            "chats_reviewed": reviewed,
        },
    }


def change_priority(conn, ticket_id: str, priority: str, actor: str) -> dict:
    """Set the priority (the SLA due times are recalculated from
    creation). The caller checks the ticket exists and is in scope."""
    lifecycle.set_priority(conn, ticket_id, priority, actor)
    row = conn.execute(f"SELECT {sla.SLA_COLUMNS} FROM tickets WHERE ticket_id = ?", (ticket_id,)).fetchone()
    return {"ticket_id": ticket_id, "priority": row["priority"], "sla": sla.evaluate(row)}
