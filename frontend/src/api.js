import { roleFromToken } from "./lib/tokenRole";

const TOKEN_KEY = "ticketapp_token";
// Older builds stored the role next to the token; it could disagree with
// the token (another tab signed in as someone else), so it is only removed.
const LEGACY_ROLE_KEY = "ticketapp_role";
const MUST_CHANGE_KEY = "ticketapp_must_change_password";

// Where each role lands after login. The backend enforces the same
// boundaries on every endpoint; this only picks the portal.
export const HOME_FOR_ROLE = {
  customer: "/customer",
  technician: "/technician",
  manager: "/manager",
  admin: "/admin",
};

// Local dev falls through to Vite's /api proxy (vite.config.js -> :8000).
// Static Web Apps has no such proxy, so production is built with
// VITE_API_URL pointing at the App Service origin, e.g.
//   VITE_API_URL=https://<your-app>.azurewebsites.net/api
// Vite inlines import.meta.env at build time, so this is a build-time
// setting, not a runtime one.
const API_BASE = (import.meta.env.VITE_API_URL || "/api").replace(/\/+$/, "");

export function saveSession(token, mustChangePassword = false) {
  localStorage.setItem(TOKEN_KEY, token);
  localStorage.removeItem(LEGACY_ROLE_KEY);
  setMustChangePassword(mustChangePassword);
}

export function clearSession() {
  localStorage.removeItem(TOKEN_KEY);
  localStorage.removeItem(LEGACY_ROLE_KEY);
  localStorage.removeItem(MUST_CHANGE_KEY);
}

// Another tab signed in or out (localStorage is shared by every tab): the
// token this tab sends changed, so the portal it shows may be the wrong one.
export function onSessionChange(callback) {
  const listener = (event) => {
    if (event.key === TOKEN_KEY || event.key === null) callback();
  };
  window.addEventListener("storage", listener);
  return () => window.removeEventListener("storage", listener);
}

export function setMustChangePassword(value) {
  if (value) localStorage.setItem(MUST_CHANGE_KEY, "1");
  else localStorage.removeItem(MUST_CHANGE_KEY);
}

export function getMustChangePassword() {
  return localStorage.getItem(MUST_CHANGE_KEY) === "1";
}

export function getToken() {
  return localStorage.getItem(TOKEN_KEY);
}

// The role of the token this browser sends, so the portal shown always
// matches what the server will allow.
export function getRole() {
  return roleFromToken(getToken());
}

// Query string from an object, leaving out empty values.
function query(filters) {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(filters)) if (value) params.set(key, value);
  return params.toString();
}

async function request(path, { method = "GET", body, auth = false } = {}) {
  const headers = { "Content-Type": "application/json" };
  if (auth) {
    const token = getToken();
    if (token) headers.Authorization = `Bearer ${token}`;
  }

  const res = await fetch(`${API_BASE}${path}`, {
    method,
    headers,
    body: body ? JSON.stringify(body) : undefined,
  });

  if (!res.ok) {
    let detail = res.statusText;
    try {
      const data = await res.json();
      detail = data.detail || detail;
    } catch {
      /* no JSON body */
    }
    const error = new Error(detail);
    // 429s say how long to wait (Retry-After, seconds): sign-in counts it down.
    error.status = res.status;
    error.retryAfter = Number(res.headers.get("Retry-After")) || null;
    throw error;
  }

  if (res.status === 204) return null;
  return res.json();
}

async function errorDetail(res) {
  try {
    const data = await res.json();
    return typeof data.detail === "string" ? data.detail : res.statusText;
  } catch {
    return res.statusText;
  }
}

// Multipart upload; the browser sets the boundary Content-Type itself.
async function upload(path, formData) {
  const res = await fetch(`${API_BASE}${path}`, {
    method: "POST",
    headers: { Authorization: `Bearer ${getToken()}` },
    body: formData,
  });
  if (!res.ok) throw new Error(await errorDetail(res));
  return res.json();
}

// Attachments need the bearer token, so a plain <a href> can't fetch them.
async function downloadFile(path, filename) {
  const res = await fetch(`${API_BASE}${path}`, {
    headers: { Authorization: `Bearer ${getToken()}` },
  });
  if (!res.ok) throw new Error(await errorDetail(res));
  const url = URL.createObjectURL(await res.blob());
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export const api = {
  // Customer signup is the only public signup; staff are created by the admin.
  customerSignup: (name, email, password) =>
    request("/auth/customer/signup", { method: "POST", body: { name, email, password } }),
  login: (email, password) =>
    request("/auth/login", { method: "POST", body: { email, password } }),
  me: () => request("/auth/me", { auth: true }),
  changePassword: (current_password, new_password) =>
    request("/auth/change-password", {
      method: "POST",
      body: { current_password, new_password },
      auth: true,
    }),

  categories: () => request("/categories"),
  meta: () => request("/meta"),
  ticketsMine: () => request("/tickets/mine", { auth: true }),
  // Raise a ticket: email-style, no chat.
  ticketsCreate: ({ subject, category, priority, description }) =>
    request("/tickets", {
      method: "POST",
      body: { subject, category: category || null, priority, description },
      auth: true,
    }),
  ticketDetail: (ticketId) => request(`/tickets/${ticketId}`, { auth: true }),
  ticketReply: (ticketId, message) =>
    request(`/tickets/${ticketId}/reply`, { method: "POST", body: { message }, auth: true }),
  ticketReopen: (ticketId) =>
    request(`/tickets/${ticketId}/reopen`, { method: "POST", auth: true }),
  uploadAttachments: (ticketId, messageId, files) => {
    const form = new FormData();
    form.append("message_id", messageId);
    for (const file of files) form.append("files", file);
    return upload(`/tickets/${ticketId}/attachments`, form);
  },
  downloadAttachment: (ticketId, attachment) =>
    downloadFile(
      `/tickets/${ticketId}/attachments/${attachment.attachment_id}`,
      attachment.filename,
    ),

  // AI chat sessions: separate from tickets until escalated.
  chatsList: () => request("/chats", { auth: true }),
  chatStart: ({ issue, category, contact_name }) =>
    request("/chats", {
      method: "POST",
      body: { issue, category: category || null, contact_name },
      auth: true,
    }),
  chatGet: (sessionId) => request(`/chats/${sessionId}`, { auth: true }),
  chatSend: (sessionId, message) =>
    request(`/chats/${sessionId}/messages`, { method: "POST", body: { message }, auth: true }),
  chatResolve: (sessionId) => request(`/chats/${sessionId}/resolve`, { method: "POST", auth: true }),
  chatEscalate: (sessionId, subject) =>
    request(`/chats/${sessionId}/escalate`, {
      method: "POST",
      body: { subject: subject || null },
      auth: true,
    }),

  chatReviews: (status) =>
    request(`/chat-reviews${status ? `?status=${status}` : ""}`, { auth: true }),
  chatReviewUpdate: (reviewId, status) =>
    request(`/chat-reviews/${reviewId}`, { method: "POST", body: { status }, auth: true }),

  // Technician workspace + manager oversight (backend/staff_tickets.py).
  staffTickets: ({ view, q, priority, status, ticket_type, period, sla } = {}) =>
    request(`/staff/tickets?${query({ view: view || "unassigned", q, priority, status, ticket_type, period, sla })}`, {
      auth: true,
    }),
  staffTicketCounts: ({ q, priority, status, ticket_type } = {}) =>
    request(`/staff/tickets/counts?${query({ q, priority, status, ticket_type })}`, { auth: true }),
  staffDashboard: (period) => request(`/staff/dashboard?${query({ period })}`, { auth: true }),
  // Chats, read-only (technicians: all; managers: their department).
  staffChats: ({ filter, q } = {}) => request(`/staff/chats?${query({ filter, q })}`, { auth: true }),
  staffChat: (sessionId) => request(`/staff/chats/${encodeURIComponent(sessionId)}`, { auth: true }),
  staffTicket: (ticketId) => request(`/staff/tickets/${ticketId}`, { auth: true }),
  staffClaim: (ticketId) =>
    request(`/staff/tickets/${ticketId}/claim`, { method: "POST", auth: true }),
  staffSetStatus: (ticketId, status) =>
    request(`/staff/tickets/${ticketId}/status`, { method: "POST", body: { status }, auth: true }),
  staffMessage: (ticketId, { body, visibility, subject, set_status }) =>
    request(`/staff/tickets/${ticketId}/messages`, {
      method: "POST",
      body: { body, visibility, subject: subject || null, set_status: set_status || null },
      auth: true,
    }),
  managerOverview: () => request("/manager/overview", { auth: true }),
  // Manager pages, limited to the manager's department (backend/manager.py).
  managerDashboard: (period) => request(`/manager/dashboard?${query({ period })}`, { auth: true }),
  managerSla: ({ period, priority } = {}) => request(`/manager/sla?${query({ period, priority })}`, { auth: true }),
  managerTickets: (filters = {}) => request(`/manager/tickets?${query(filters)}`, { auth: true }),
  managerReassignTicket: (ticketId, technicianId) =>
    request(`/manager/tickets/${ticketId}/reassign`, {
      method: "POST",
      body: { technician_id: technicianId || null },
      auth: true,
    }),
  managerSetTicketPriority: (ticketId, priority) =>
    request(`/manager/tickets/${ticketId}/priority`, { method: "POST", body: { priority }, auth: true }),

  // AI incident correlation (backend/incidents.py): managers, and
  // technicians for incidents assigned to them.
  incidents: (includeDismissed = false) =>
    request(`/incidents${includeDismissed ? "?include_dismissed=true" : ""}`, { auth: true }),
  incident: (incidentId) => request(`/incidents/${incidentId}`, { auth: true }),
  incidentReview: (incidentId, action, note) =>
    request(`/incidents/${incidentId}/review`, { method: "POST", body: { action, note }, auth: true }),
  incidentDepartments: (incidentId, department_ids) =>
    request(`/incidents/${incidentId}/departments`, {
      method: "PUT",
      body: { department_ids },
      auth: true,
    }),
  incidentsRun: () => request("/incidents/run", { method: "POST", auth: true }),
  incidentAssignee: (incidentId, technician_id) =>
    request(`/incidents/${incidentId}/assignee`, {
      method: "PUT",
      body: { technician_id: technician_id || null },
      auth: true,
    }),
  // Post-incident summary (backend/incident_resolution.py).
  incidentDraft: (incidentId, { resolution_note, fixed_at, root_cause }) =>
    request(`/incidents/${incidentId}/resolution/draft`, {
      method: "POST",
      body: { resolution_note, fixed_at, root_cause: root_cause || null },
      auth: true,
    }),
  incidentSaveSummary: (incidentId, { customer_summary, internal_summary, visibility }) =>
    request(`/incidents/${incidentId}/resolution/summary`, {
      method: "PUT",
      body: { customer_summary, internal_summary, visibility },
      auth: true,
    }),
  incidentSend: (incidentId, customer_summary, mark_tickets_resolved) =>
    request(`/incidents/${incidentId}/resolution/send`, {
      method: "POST",
      body: { customer_summary, mark_tickets_resolved },
      auth: true,
    }),
  incidentVisibility: (incidentId, visibility) =>
    request(`/incidents/${incidentId}/visibility`, { method: "PUT", body: { visibility }, auth: true }),
  publicIncidents: () => request("/public/incidents"),

  adminStaff: () => request("/admin/staff", { auth: true }),
  adminUpdateStaff: (staffId, changes) =>
    request(`/admin/staff/${staffId}`, { method: "PATCH", body: changes, auth: true }),

  // Users (customers, technicians, managers). Create and reset return the
  // generated temporary password once (temporary_password).
  adminUsers: (filters = {}) => request(`/admin/users?${query(filters)}`, { auth: true }),
  adminCreateUser: ({ name, email, role, department_id }) =>
    request("/admin/users", {
      method: "POST",
      body: { name, email, role, department_id: department_id || null },
      auth: true,
    }),
  adminUpdateUser: (userId, changes) =>
    request(`/admin/users/${userId}`, { method: "PATCH", body: changes, auth: true }),
  adminSetUserActive: (userId, active) =>
    request(`/admin/users/${userId}/${active ? "activate" : "deactivate"}`, { method: "POST", auth: true }),
  adminResetUserPassword: (userId) =>
    request(`/admin/users/${userId}/reset-password`, { method: "POST", auth: true }),

  adminSettings: () => request("/admin/settings", { auth: true }),
  adminSaveSettings: (section, values) =>
    request(`/admin/settings/${section}`, { method: "PUT", body: values, auth: true }),
  adminResetSettings: (section) =>
    request(`/admin/settings/${section}`, { method: "DELETE", auth: true }),

  adminAudit: (filters = {}) => {
    const params = new URLSearchParams();
    for (const [key, value] of Object.entries(filters)) if (value) params.set(key, value);
    return request(`/admin/audit?${params}`, { auth: true });
  },

  adminDepartments: () => request("/admin/departments", { auth: true }),
  adminCreateDepartment: (name, categories) =>
    request("/admin/departments", { method: "POST", body: { name, categories }, auth: true }),
  adminUpdateDepartment: (departmentId, name, categories) =>
    request(`/admin/departments/${departmentId}`, {
      method: "PUT",
      body: { name, categories },
      auth: true,
    }),
  adminDeleteDepartment: (departmentId) =>
    request(`/admin/departments/${departmentId}`, { method: "DELETE", auth: true }),

  // Try a Ticket (backend/try_ticket.py): technicians and managers.
  tryATicket: (ticket_text, channel, customer_id) =>
    request("/try-a-ticket", {
      method: "POST",
      body: { ticket_text, channel, customer_id: customer_id || undefined },
      auth: true,
    }),

  // Public, read-only (the /docs page).
  routingPolicy: () => request("/public/routing-policy"),

  // Knowledge base (technicians and managers; managers run sources and
  // decide; the backend enforces both).
  kbSources: () => request("/kb/sources", { auth: true }),
  kbCreateSource: (body) => request("/kb/sources", { method: "POST", body, auth: true }),
  kbUploadSource: ({ name, file, publicConfirmed, licenceNote }) => {
    const form = new FormData();
    form.append("name", name);
    form.append("public_confirmed", publicConfirmed ? "true" : "false");
    form.append("licence_note", licenceNote || "");
    form.append("file", file);
    return upload("/kb/sources/upload", form);
  },
  kbTextSource: (body) => request("/kb/sources/text", { method: "POST", body, auth: true }),
  kbUploadVersion: (sourceId, file) => {
    const form = new FormData();
    form.append("file", file);
    return upload(`/kb/sources/${sourceId}/upload`, form);
  },
  kbTextVersion: (sourceId, text) =>
    request(`/kb/sources/${sourceId}/text`, { method: "POST", body: { text }, auth: true }),
  kbSourceRuns: (sourceId) => request(`/kb/sources/${sourceId}/runs`, { auth: true }),
  kbEstimate: (sourceId) => request(`/kb/sources/${sourceId}/estimate`, { method: "POST", auth: true }),
  kbStartRun: (runId, expectedModelCalls) =>
    request(`/kb/runs/${runId}/start`, {
      method: "POST",
      body: { expected_model_calls: expectedModelCalls },
      auth: true,
    }),
  kbRun: (runId) => request(`/kb/runs/${runId}`, { auth: true }),
  kbEntries: (filters = {}) => request(`/kb/entries?${query(filters)}`, { auth: true }),
  kbEntry: (entryId) => request(`/kb/entries/${encodeURIComponent(entryId)}`, { auth: true }),
  kbEditEntry: (entryId, body) =>
    request(`/kb/entries/${encodeURIComponent(entryId)}`, { method: "PATCH", body, auth: true }),
  kbDecideEntry: (entryId, decision, version, note, acknowledgeIncomplete = false) =>
    request(`/kb/entries/${encodeURIComponent(entryId)}/${decision}`, {
      method: "POST",
      body: { version, note, acknowledge_incomplete: acknowledgeIncomplete },
      auth: true,
    }),
  kbTerms: (status = "all") => request(`/kb/terms?${query({ status })}`, { auth: true }),
  kbProposeTerm: (body) => request("/kb/terms", { method: "POST", body, auth: true }),
  kbTermAction: (termId, action, body) =>
    request(`/kb/terms/${termId}/${action}`, { method: "POST", body, auth: true }),
  kbCategories: () => request("/kb/categories", { auth: true }),
  kbCategoryAction: (name, action, body) =>
    request(`/kb/categories/${encodeURIComponent(name)}/${action}`, { method: "POST", body, auth: true }),
};
