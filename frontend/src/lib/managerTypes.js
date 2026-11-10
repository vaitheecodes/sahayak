/* Manager types (backend/permissions.py). The server decides what each may
 * do; these are the names and one-line hints people read. */
export const MANAGER_TYPES = {
  tech_lead: "Tech Lead",
  product_manager: "Product Manager",
  incident_manager: "Incident Manager",
  platform_lead: "Platform Lead",
};

export const MANAGER_TYPE_HINTS = {
  tech_lead: "Their department's tickets; assigns them to its support engineers.",
  product_manager: "Their department's tickets, like a Tech Lead.",
  incident_manager: "Their department's tickets and incidents, like a Tech Lead.",
  platform_lead: "Every department: picks one or all, reassigns across them, sees Teams. A department is optional.",
};

export function managerTypeLabel(type) {
  return MANAGER_TYPES[type] || MANAGER_TYPES.tech_lead;
}
