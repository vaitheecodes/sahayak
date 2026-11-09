"""Manager pages: everything limited to the manager's own department.

A manager belongs to one department (staff.department_id); a ticket or
chat is in it when its category (COALESCE(category, requested_category))
is one the department owns. Every endpoint here checks that, including a
direct call with another department's ticket id (403). Technicians "work"
a department when the admin gave them that department_id; only they can
be assigned its tickets.

  GET  /api/manager/dashboard?period=          KPIs, workload, created vs resolved, open by priority
  GET  /api/manager/sla?period=&priority=      compliance and the near-breach list
  GET  /api/manager/tickets?q=&status=&priority=   Department tickets
  GET  /api/manager/technicians                 the department's technicians, with counts
  POST /api/manager/tickets/{id}/reassign       {technician_id | null}
  POST /api/manager/tickets/{id}/priority       {priority}

The aggregation is backend/admin_reports.py's (a category scope); periods
are backend/periods.py presets in IST.
"""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from backend import admin_reports, auth, db, periods, sla
from backend import ticket_lifecycle as lifecycle
from backend.conversation import insert_ticket_message, subject_for
from backend.staff_tickets import manager_department

router = APIRouter()

_manager = auth.get_current_manager

Priority = Literal["low", "medium", "high", "urgent"]
Status = Literal["open", "in_progress", "pending_customer", "resolved", "closed"]
PeriodPreset = Literal[periods.PRESETS]  # type: ignore[valid-type]


# The SLA columns not already in the Department tickets SELECT.
_SLA_EXTRA = ", ".join("t." + c.strip() for c in sla.SLA_COLUMNS.split(",")
                       if c.strip() not in ("created_at", "status", "priority"))


class ReassignRequest(BaseModel):
    technician_id: str | None = None


class PriorityRequest(BaseModel):
    priority: Priority


def _department(manager_id: str) -> dict | None:
    conn = db.get_connection()
    try:
        return manager_department(conn, manager_id)
    finally:
        conn.close()


def _department_out(department: dict | None) -> dict | None:
    return {"department_id": department["department_id"], "name": department["name"],
            "categories": sorted(department["categories"])} if department else None


def _technicians(conn, department_id: str | None) -> list[dict]:
    if not department_id:
        return []
    return [dict(r) for r in conn.execute(
        "SELECT s.staff_id, s.name, s.email, "
        "COALESCE(SUM(CASE WHEN t.status NOT IN ('resolved', 'closed') THEN 1 ELSE 0 END), 0) AS active_count, "
        "COALESCE(SUM(CASE WHEN t.status = 'resolved' THEN 1 ELSE 0 END), 0) AS resolved_count "
        "FROM staff s LEFT JOIN tickets t ON t.assigned_technician_id = s.staff_id AND t.route = 'human' "
        "WHERE s.role = 'technician' AND s.active = 1 AND s.department_id = ? "
        "GROUP BY s.staff_id, s.name, s.email ORDER BY lower(s.name)", (department_id,))]


@router.get("/api/manager/dashboard")
def manager_dashboard(period: PeriodPreset = periods.DEFAULT, manager_id: str = Depends(_manager)):
    department = _department(manager_id)
    conn = db.get_connection()
    try:
        technicians = _technicians(conn, department and department["department_id"])
    finally:
        conn.close()
    data = admin_reports.dashboard_data(periods.period_range(period), department["categories"] if department else set(),
                                        technicians)
    return {"department": _department_out(department), **data}


@router.get("/api/manager/sla")
def manager_sla(period: PeriodPreset = periods.DEFAULT, priority: Priority | None = None,
                manager_id: str = Depends(_manager)):
    department = _department(manager_id)
    data = admin_reports.sla_data(periods.period_range(period), department["categories"] if department else set(), priority)
    return {"department": _department_out(department), **data}


@router.get("/api/manager/tickets")
def manager_tickets(q: str | None = Query(default=None, max_length=200), status: Status | None = None,
                    priority: Priority | None = None, manager_id: str = Depends(_manager)):
    """The department's tickets (AI-handled ones too, without reassign),
    newest first."""
    department = _department(manager_id)
    params: list = []
    clauses = [admin_reports.scope_sql(department["categories"] if department else set(), params)]
    if q and q.strip():
        clauses.append("(lower(t.ticket_id) LIKE lower(?) OR lower(t.subject) LIKE lower(?) "
                       "OR lower(t.ticket_text) LIKE lower(?) OR lower(c.name) LIKE lower(?) "
                       "OR lower(c.email) LIKE lower(?))")
        params.extend([f"%{q.strip()}%"] * 5)
    if status:
        clauses.append("t.status = ?")
        params.append(status)
    if priority:
        clauses.append("t.priority = ?")
        params.append(priority)
    conn = db.get_connection()
    try:
        rows = conn.execute(
            "SELECT t.ticket_id, t.subject, t.ticket_text, t.status, t.route, t.priority, t.ticket_type, "
            "COALESCE(t.category, t.requested_category) AS category, t.confidence, t.created_at, "
            "t.assigned_technician_id, c.name AS customer_name, c.email AS customer_email, "
            f"s.name AS technician_name, {_SLA_EXTRA} "
            "FROM tickets t JOIN customers c ON c.customer_id = t.customer_id "
            "LEFT JOIN staff s ON s.staff_id = t.assigned_technician_id "
            f"WHERE {' AND '.join(clauses)} ORDER BY t.created_at DESC LIMIT 500", params).fetchall()
        technicians = _technicians(conn, department and department["department_id"])
    finally:
        conn.close()
    return {
        "department": _department_out(department),
        "technicians": technicians,
        "tickets": [{
            **{k: r[k] for k in ("ticket_id", "status", "route", "priority", "ticket_type", "category",
                                 "confidence", "created_at", "assigned_technician_id", "customer_name",
                                 "customer_email", "technician_name", "ticket_text")},
            "subject": subject_for(r),
            "sla": sla.evaluate(r),
        } for r in rows],
    }


@router.get("/api/manager/technicians")
def manager_technicians(manager_id: str = Depends(_manager)):
    department = _department(manager_id)
    conn = db.get_connection()
    try:
        return {"department": _department_out(department),
                "technicians": _technicians(conn, department and department["department_id"])}
    finally:
        conn.close()


def _department_ticket(conn, ticket_id: str, department: dict | None):
    ticket = conn.execute("SELECT * FROM tickets WHERE ticket_id = ?", (ticket_id,)).fetchone()
    if ticket is None:
        raise HTTPException(status_code=404, detail="Ticket not found")
    category = ticket["category"] or ticket["requested_category"]
    if department is None or category not in department["categories"]:
        raise HTTPException(status_code=403, detail="Ticket is outside your department")
    return ticket


@router.post("/api/manager/tickets/{ticket_id}/reassign")
def manager_reassign(ticket_id: str, body: ReassignRequest, manager_id: str = Depends(_manager)):
    """(Re)assign a human-routed department ticket to a technician who
    works the department, or return it to the unassigned queue
    (technician_id=null). Logged in assignment history and the audit log."""
    department = _department(manager_id)
    conn = db.get_connection()
    try:
        ticket = _department_ticket(conn, ticket_id, department)
        if ticket["route"] != "human":
            raise HTTPException(status_code=400,
                                detail="Only tickets routed to the support team can be (re)assigned")
        if body.technician_id:
            technician = conn.execute(
                "SELECT name, department_id FROM staff WHERE staff_id = ? AND role = 'technician' AND active = 1",
                (body.technician_id,)).fetchone()
            if technician is None:
                raise HTTPException(status_code=404, detail="Technician not found")
            if technician["department_id"] != department["department_id"]:
                raise HTTPException(status_code=400, detail="That technician doesn't work in your department")
            note = f"Reassigned to {technician['name']} by a manager."
        else:
            note = "Returned to the unassigned queue by a manager."
        if lifecycle.set_assignee(conn, ticket_id, body.technician_id, manager_id):
            insert_ticket_message(conn, ticket_id, "system", note, customer_visible=False)
            if body.technician_id and ticket["status"] == "open":
                lifecycle.set_status(conn, ticket_id, "in_progress", manager_id)
            elif not body.technician_id and ticket["status"] == "in_progress":
                lifecycle.set_status(conn, ticket_id, "open", manager_id)
        conn.commit()
        return {"ticket_id": ticket_id, "assigned_technician_id": body.technician_id}
    finally:
        conn.close()


@router.post("/api/manager/tickets/{ticket_id}/priority")
def manager_priority(ticket_id: str, body: PriorityRequest, manager_id: str = Depends(_manager)):
    department = _department(manager_id)
    conn = db.get_connection()
    try:
        _department_ticket(conn, ticket_id, department)
        result = admin_reports.change_priority(conn, ticket_id, body.priority, manager_id)
        conn.commit()
        return result
    finally:
        conn.close()
