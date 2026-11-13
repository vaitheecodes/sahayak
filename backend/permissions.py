"""What each kind of manager may do: one table.

Managers (role "manager") have a type, staff.manager_type:

  tech_lead, product_manager, incident_manager
      peers: their own department (the categories it owns), as managers
      always had; they assign its tickets to its support engineers
  platform_lead
      a manager of managers: every department, reassigns across them,
      sees the Teams page

The type is read from the database on every request (auth._load_user),
never from the token, so a change by the admin takes effect on the
manager's next request. Only the admin sets it (Users page); the admin
account itself never has one (it is not in `staff`). Changing what a type
may do is one line in PERMISSIONS.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from fastapi import HTTPException

MANAGER_TYPES = ("tech_lead", "product_manager", "incident_manager", "platform_lead")
DEFAULT_MANAGER_TYPE = "tech_lead"
LABELS = {
    "tech_lead": "Tech Lead",
    "product_manager": "Product Manager",
    "incident_manager": "Incident Manager",
    "platform_lead": "Platform Lead",
}

DEPARTMENT = "department"  # the manager's own department
ALL = "all"                # every department

# tickets:    tickets, chats, chat reviews, SLA and the dashboard
# reassign:   which support engineers a ticket may be handed to
# incidents:  which incidents are listed (ALL for incident_manager widens it)
# teams:      the Teams page (every department's managers and engineers)
# unanswered: the Unanswered questions list (KB gaps; question text and count only)
PERMISSIONS: dict[str, dict] = {
    "tech_lead":        {"tickets": DEPARTMENT, "reassign": DEPARTMENT, "incidents": DEPARTMENT, "teams": False, "unanswered": True},
    "product_manager":  {"tickets": DEPARTMENT, "reassign": DEPARTMENT, "incidents": DEPARTMENT, "teams": False, "unanswered": True},
    "incident_manager": {"tickets": DEPARTMENT, "reassign": DEPARTMENT, "incidents": DEPARTMENT, "teams": False, "unanswered": True},
    "platform_lead":    {"tickets": ALL, "reassign": ALL, "incidents": ALL, "teams": True, "unanswered": True},
}


def manager_type(user: dict) -> str | None:
    """The type of a manager (a missing one counts as a Tech Lead); None
    for anyone who isn't a manager."""
    if user.get("role") != "manager":
        return None
    kind = user.get("manager_type")
    return kind if kind in PERMISSIONS else DEFAULT_MANAGER_TYPE


def allowed(user: dict, permission: str):
    """The PERMISSIONS value for this user (None for a non-manager)."""
    kind = manager_type(user)
    return PERMISSIONS[kind][permission] if kind else None


def sees_all(user: dict, permission: str = "tickets") -> bool:
    return allowed(user, permission) == ALL


# ---------------------------------------------------------------------------
# Scope: which tickets and chats a manager sees
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Scope:
    categories: frozenset[str] | None  # None: every ticket (also those in no department)
    department: dict | None            # the department in view; None: all of them


def _department(conn, where: str, value: str) -> dict | None:
    row = conn.execute(f"SELECT d.department_id, d.name, d.categories FROM departments d {where}",
                       (value,)).fetchone()
    return {"department_id": row["department_id"], "name": row["name"],
            "categories": set(json.loads(row["categories"]))} if row else None


def own_department(conn, staff_id: str) -> dict | None:
    """The staff member's one department {department_id, name, categories},
    or None while the admin hasn't given them one."""
    return _department(conn, "JOIN staff s ON s.department_id = d.department_id WHERE s.staff_id = ?", staff_id)


def manager_scope(conn, user: dict, department_id: str | None = None) -> Scope:
    """A manager's tickets: their own department's categories, or with
    tickets: ALL every ticket, narrowed to one department by
    `department_id` ("all" or None: every one). Only a manager whose type
    sees all may pick a department (403 otherwise)."""
    if not sees_all(user):
        if department_id is not None:
            raise HTTPException(status_code=403, detail="Only a Platform Lead can pick a department")
        own = own_department(conn, user["id"])
        return Scope(frozenset(own["categories"]) if own else frozenset(), own)
    if department_id in (None, ALL):
        return Scope(None, None)
    picked = _department(conn, "WHERE d.department_id = ?", department_id)
    if picked is None:
        raise HTTPException(status_code=404, detail="Department not found")
    return Scope(frozenset(picked["categories"]), picked)


def in_scope(scope: Scope, category: str | None) -> bool:
    return scope.categories is None or category in scope.categories
