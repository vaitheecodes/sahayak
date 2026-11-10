"""Manager pages: everything limited to the manager's scope.

A manager belongs to one department (staff.department_id); a ticket or
chat is in it when its category (COALESCE(category, requested_category))
is one the department owns. Every endpoint here checks that, including a
direct call with another department's ticket id (403). Technicians "work"
a department when the admin gave them that department_id; only they can
be assigned its tickets.

A Platform Lead (backend/permissions.py) sees every department, may narrow
the pages to one (`department=<id>`, or `all`; anyone else gets 403 for
passing it), may hand a ticket to any active support engineer (a
cross-department reassign doesn't move the ticket: it stays with the
department that owns its category, and is audited with who, from and to),
and sees the Teams page.

  GET  /api/manager/dashboard?period=&department=   KPIs, workload, created vs resolved, open by priority
  GET  /api/manager/sla?period=&priority=&department=   compliance and the near-breach list
  GET  /api/manager/tickets?q=&status=&priority=&period=&assigned=&sla=&department=   Department tickets
  GET  /api/manager/technicians?department=     support engineers one can assign, with counts
  GET  /api/manager/teams                       Platform Lead: each department's managers and engineers
  POST /api/manager/tickets/{id}/reassign       {technician_id | null}
  POST /api/manager/tickets/{id}/priority       {priority}

The aggregation is backend/admin_reports.py's (a category scope); periods
are backend/periods.py presets in IST.
"""

from __future__ import annotations

import json
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from backend import admin_reports, audit, auth, db, periods, permissions, sla
from backend import ticket_lifecycle as lifecycle
from backend.conversation import insert_ticket_message, subject_for
from backend.permissions import Scope

router = APIRouter()

_manager = auth.require_user("manager")
# A department id, or "all" (Platform Lead only).
DepartmentParam = Query(default=None, max_length=64)

Priority = Literal["low", "medium", "high", "urgent"]
# "new" = open with nobody assigned (not a stored status).
Status = Literal["new", "open", "in_progress", "pending_customer", "resolved", "closed"]
PeriodPreset = Literal[periods.PRESETS]  # type: ignore[valid-type]
SlaState = Literal["breached", "at_risk"]


# The SLA columns not already in the Department tickets SELECT.
_SLA_EXTRA = ", ".join("t." + c.strip() for c in sla.SLA_COLUMNS.split(",")
                       if c.strip() not in ("created_at", "status", "priority"))


class ReassignRequest(BaseModel):
    technician_id: str | None = None


class PriorityRequest(BaseModel):
    priority: Priority


def _scope(user: dict, department: str | None = None) -> Scope:
    conn = db.get_connection()
    try:
        return permissions.manager_scope(conn, user, department)
    finally:
        conn.close()


def _department_out(department: dict | None) -> dict | None:
    return {"department_id": department["department_id"], "name": department["name"],
            "categories": sorted(department["categories"])} if department else None


def _technicians(conn, scope: Scope) -> list[dict]:
    """The active support engineers of the department in view (all of them
    when the scope is every department), with their counts."""
    if scope.categories is not None and not scope.department:
        return []
    where, params = ("AND s.department_id = ? ", (scope.department["department_id"],)) if scope.department else ("", ())
    return [dict(r) for r in conn.execute(
        "SELECT s.staff_id, s.name, s.email, s.department_id, d.name AS department_name, "
        "COALESCE(SUM(CASE WHEN t.status NOT IN ('resolved', 'closed') THEN 1 ELSE 0 END), 0) AS active_count, "
        "COALESCE(SUM(CASE WHEN t.status = 'resolved' THEN 1 ELSE 0 END), 0) AS resolved_count "
        "FROM staff s LEFT JOIN tickets t ON t.assigned_technician_id = s.staff_id AND t.route = 'human' "
        "LEFT JOIN departments d ON d.department_id = s.department_id "
        f"WHERE s.role = 'technician' AND s.active = 1 {where}"
        "GROUP BY s.staff_id, s.name, s.email, s.department_id, d.name ORDER BY lower(s.name)", params)]


def _out(scope: Scope) -> dict:
    return {"department": _department_out(scope.department), "all_departments": scope.categories is None}


@router.get("/api/manager/dashboard")
def manager_dashboard(period: PeriodPreset = periods.DEFAULT, department: str | None = DepartmentParam,
                      user: dict = Depends(_manager)):
    scope = _scope(user, department)
    conn = db.get_connection()
    try:
        technicians = _technicians(conn, scope)
    finally:
        conn.close()
    data = admin_reports.dashboard_data(periods.period_range(period), scope.categories, technicians)
    return {**_out(scope), **data}


@router.get("/api/manager/sla")
def manager_sla(period: PeriodPreset = periods.DEFAULT, priority: Priority | None = None,
                department: str | None = DepartmentParam, user: dict = Depends(_manager)):
    scope = _scope(user, department)
    data = admin_reports.sla_data(periods.period_range(period), scope.categories, priority)
    return {**_out(scope), **data}


@router.get("/api/manager/tickets")
def manager_tickets(q: str | None = Query(default=None, max_length=200), status: Status | None = None,
                    priority: Priority | None = None, period: PeriodPreset | None = None,
                    assigned: bool | None = None, sla_state: SlaState | None = Query(default=None, alias="sla"),
                    department: str | None = DepartmentParam, user: dict = Depends(_manager)):
    """The department's tickets (AI-handled ones too, without reassign),
    newest first. `period`: created in that preset; status "new": open with
    nobody assigned; `assigned`: someone has it (true) or nobody (false);
    `sla`: in that SLA state now (worked out before the 500 limit)."""
    scope = _scope(user, department)
    params: list = []
    clauses = [admin_reports.scope_sql(scope.categories, params)]
    if q and q.strip():
        clauses.append("(lower(t.ticket_id) LIKE lower(?) OR lower(t.subject) LIKE lower(?) "
                       "OR lower(t.ticket_text) LIKE lower(?) OR lower(c.name) LIKE lower(?) "
                       "OR lower(c.email) LIKE lower(?))")
        params.extend([f"%{q.strip()}%"] * 5)
    if status == "new":
        clauses.append("t.status = 'open' AND t.assigned_technician_id IS NULL")
    elif status:
        clauses.append("t.status = ?")
        params.append(status)
    if priority:
        clauses.append("t.priority = ?")
        params.append(priority)
    if assigned is not None:
        clauses.append(f"t.assigned_technician_id IS {'NOT ' if assigned else ''}NULL")
    if period:
        p = periods.period_range(period)
        clauses.append("t.created_at >= ? AND t.created_at < ?")
        params.extend([sla.iso(p.start), sla.iso(p.end)])
    if sla_state:
        clauses.append("t.sla_resolution_minutes IS NOT NULL")
    conn = db.get_connection()
    try:
        rows = conn.execute(
            "SELECT t.ticket_id, t.subject, t.ticket_text, t.status, t.route, t.priority, t.ticket_type, "
            "COALESCE(t.category, t.requested_category) AS category, t.confidence, t.created_at, "
            "t.assigned_technician_id, c.name AS customer_name, c.email AS customer_email, "
            f"s.name AS technician_name, {_SLA_EXTRA} "
            "FROM tickets t JOIN customers c ON c.customer_id = t.customer_id "
            "LEFT JOIN staff s ON s.staff_id = t.assigned_technician_id "
            f"WHERE {' AND '.join(clauses)} ORDER BY t.created_at DESC{'' if sla_state else ' LIMIT 500'}",
            params).fetchall()
        rows = admin_reports.in_sla_state(rows, sla_state)[:500]
        technicians = _technicians(conn, scope)
    finally:
        conn.close()
    return {
        **_out(scope),
        "technicians": technicians,
        "tickets": [{
            **{k: r[k] for k in ("ticket_id", "status", "route", "priority", "ticket_type", "category",
                                 "confidence", "created_at", "assigned_technician_id", "customer_name",
                                 "customer_email", "technician_name", "ticket_text")},
            "subject": subject_for(r),
            "sla": e,
        } for r, e in rows],
    }


@router.get("/api/manager/technicians")
def manager_technicians(department: str | None = DepartmentParam, user: dict = Depends(_manager)):
    scope = _scope(user, department)
    conn = db.get_connection()
    try:
        return {**_out(scope), "technicians": _technicians(conn, scope)}
    finally:
        conn.close()


@router.get("/api/manager/teams")
def manager_teams(user: dict = Depends(_manager)):
    """Every department's managers (with their type) and support engineers
    (with open and resolved counts), then the people in no department.
    Only for a manager whose type has `teams` (a Platform Lead)."""
    if not permissions.allowed(user, "teams"):
        raise HTTPException(status_code=403, detail="Only a Platform Lead can see every team")
    conn = db.get_connection()
    try:
        people = [dict(r) for r in conn.execute(
            "SELECT s.staff_id, s.name, s.email, s.role, s.manager_type, s.department_id, "
            "COALESCE(SUM(CASE WHEN t.status NOT IN ('resolved', 'closed') THEN 1 ELSE 0 END), 0) AS open, "
            "COALESCE(SUM(CASE WHEN t.status = 'resolved' THEN 1 ELSE 0 END), 0) AS resolved "
            "FROM staff s LEFT JOIN tickets t ON t.assigned_technician_id = s.staff_id AND t.route = 'human' "
            "WHERE s.active = 1 GROUP BY s.staff_id, s.name, s.email, s.role, s.manager_type, s.department_id "
            "ORDER BY lower(s.name)")]
        departments = [dict(r) for r in conn.execute("SELECT department_id, name FROM departments ORDER BY name")]
    finally:
        conn.close()

    def team(department_id: str | None) -> dict:
        members = [p for p in people if p["department_id"] == department_id]
        return {
            "managers": [{k: p[k] for k in ("staff_id", "name", "email", "manager_type")}
                         for p in members if p["role"] == "manager"],
            "engineers": [{k: p[k] for k in ("staff_id", "name", "email", "open", "resolved")}
                          for p in members if p["role"] == "technician"],
        }

    return {"departments": [{**d, **team(d["department_id"])} for d in departments],
            "no_department": team(None)}


def _department_ticket(conn, ticket_id: str, scope: Scope):
    ticket = conn.execute("SELECT * FROM tickets WHERE ticket_id = ?", (ticket_id,)).fetchone()
    if ticket is None:
        raise HTTPException(status_code=404, detail="Ticket not found")
    if not permissions.in_scope(scope, ticket["category"] or ticket["requested_category"]):
        raise HTTPException(status_code=403, detail="Ticket is outside your department")
    return ticket


def _owning_department(conn, category: str | None) -> str | None:
    for r in conn.execute("SELECT department_id, categories FROM departments"):
        if category in json.loads(r["categories"]):
            return r["department_id"]
    return None


@router.post("/api/manager/tickets/{ticket_id}/reassign")
def manager_reassign(ticket_id: str, body: ReassignRequest, user: dict = Depends(_manager)):
    """(Re)assign a human-routed ticket in scope to a support engineer, or
    return it to the unassigned queue (technician_id=null). With reassign
    DEPARTMENT the engineer must work the manager's department; with ALL
    (a Platform Lead) any active engineer. Logged in assignment history and
    the audit log; one to an engineer outside the ticket's department also
    as ticket.reassigned_across_departments (the ticket isn't moved)."""
    conn = db.get_connection()
    try:
        scope = permissions.manager_scope(conn, user)
        ticket = _department_ticket(conn, ticket_id, scope)
        if ticket["route"] != "human":
            raise HTTPException(status_code=400,
                                detail="Only tickets routed to the support team can be (re)assigned")
        across = None
        if body.technician_id:
            technician = conn.execute(
                "SELECT name, department_id FROM staff WHERE staff_id = ? AND role = 'technician' AND active = 1",
                (body.technician_id,)).fetchone()
            if technician is None:
                raise HTTPException(status_code=404, detail="Support engineer not found")
            if permissions.allowed(user, "reassign") != permissions.ALL and (
                    not scope.department or technician["department_id"] != scope.department["department_id"]):
                raise HTTPException(status_code=400, detail="That support engineer doesn't work in your department")
            owner = _owning_department(conn, ticket["category"] or ticket["requested_category"])
            if technician["department_id"] != owner:
                across = {"from_department_id": owner, "to_department_id": technician["department_id"]}
            note = f"Reassigned to {technician['name']} by a manager."
        else:
            note = "Returned to the unassigned queue by a manager."
        previous = ticket["assigned_technician_id"]
        if lifecycle.set_assignee(conn, ticket_id, body.technician_id, user["id"]):
            insert_ticket_message(conn, ticket_id, "system", note, customer_visible=False)
            if across:
                audit.record(conn, user["id"], "ticket.reassigned_across_departments", "ticket", ticket_id,
                             from_user=previous, to_user=body.technician_id, **across)
            if body.technician_id and ticket["status"] == "open":
                lifecycle.set_status(conn, ticket_id, "in_progress", user["id"])
            elif not body.technician_id and ticket["status"] == "in_progress":
                lifecycle.set_status(conn, ticket_id, "open", user["id"])
        conn.commit()
        return {"ticket_id": ticket_id, "assigned_technician_id": body.technician_id}
    finally:
        conn.close()


@router.post("/api/manager/tickets/{ticket_id}/priority")
def manager_priority(ticket_id: str, body: PriorityRequest, user: dict = Depends(_manager)):
    conn = db.get_connection()
    try:
        _department_ticket(conn, ticket_id, permissions.manager_scope(conn, user))
        result = admin_reports.change_priority(conn, ticket_id, body.priority, user["id"])
        conn.commit()
        return result
    finally:
        conn.close()
