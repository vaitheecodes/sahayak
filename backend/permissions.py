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
PERMISSIONS: dict[str, dict] = {
    "tech_lead":        {"tickets": DEPARTMENT, "reassign": DEPARTMENT, "incidents": DEPARTMENT, "teams": False},
    "product_manager":  {"tickets": DEPARTMENT, "reassign": DEPARTMENT, "incidents": DEPARTMENT, "teams": False},
    "incident_manager": {"tickets": DEPARTMENT, "reassign": DEPARTMENT, "incidents": DEPARTMENT, "teams": False},
    "platform_lead":    {"tickets": ALL, "reassign": ALL, "incidents": ALL, "teams": True},
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
