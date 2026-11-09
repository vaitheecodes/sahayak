import { useCallback, useEffect, useId, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { api } from "../api";
import StaffTicketView from "./StaffTicketView";
import SlaChip from "./ui/SlaChip";
import { ConfidenceChip, RouteChip, StatusChip } from "./ui/StatusChip";
import { ChatBadge } from "./ChatBadge";
import { categoryLabel } from "../utils/categories";
import { parseTicketText } from "../utils/parseTicketText";
import { PRIORITIES, PRIORITY_LABELS } from "../utils/priorities";
import { STATUS_KEYS, statusLabel } from "../utils/statusLabels";
import { absoluteTime, relativeTime } from "../utils/time";

/* Manager: Department tickets (the old admin All tickets table, limited
 * to the manager's department by the server). */

function TechnicianAssignCell({ ticket, technicians, onReassigned }) {
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  if (ticket.route !== "human") return <span className="hint">—</span>;

  async function handleChange(e) {
    const technicianId = e.target.value;
    setSaving(true);
    setError("");
    try {
      await api.managerReassignTicket(ticket.ticket_id, technicianId);
      onReassigned();
    } catch (err) {
      setError(err.message);
    } finally {
      setSaving(false);
    }
  }

  return (
    <div>
      <select
        className="select-compact"
        aria-label={`Handling technician for ticket ${ticket.ticket_id}`}
        value={ticket.assigned_technician_id || ""}
        onChange={handleChange}
        disabled={saving}
      >
        <option value="">Unassigned</option>
        {technicians.map((t) => (
          <option key={t.staff_id} value={t.staff_id}>
            {t.name}
          </option>
        ))}
      </select>
      {error && <div className="error" style={{ marginTop: "0.25rem" }}>{error}</div>}
    </div>
  );
}

/* Priority, editable by the manager: the SLA due times are recalculated
 * from the ticket's creation (backend/admin_reports.py). */
function PriorityCell({ ticket, onChanged }) {
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  async function handleChange(e) {
    setSaving(true);
    setError("");
    try {
      await api.managerSetTicketPriority(ticket.ticket_id, e.target.value);
      onChanged();
    } catch (err) {
      setError(err.message);
    } finally {
      setSaving(false);
    }
  }

  return (
    <div>
      <select
        className="select-compact"
        aria-label={`Priority of ticket ${ticket.ticket_id}`}
        value={ticket.priority}
        onChange={handleChange}
        disabled={saving}
      >
        {PRIORITIES.map((p) => (
          <option key={p} value={p}>
            {PRIORITY_LABELS[p]}
          </option>
        ))}
      </select>
      {error && <div className="error">{error}</div>}
    </div>
  );
}

/* The department's tickets, one compact row each (GET /api/manager/tickets:
 * search and status are applied by the server, so counts are the
 * department's only). Reassign offers only technicians who work the
 * department. The long text lives in the detail panel opened from the row. */
export default function DepartmentTickets() {
  const [data, setData] = useState(null);
  const [error, setError] = useState("");
  const [query, setQuery] = useState("");
  const [status, setStatus] = useState("");
  const [params] = useSearchParams();
  // ?open=<id> (a link from Chats) opens that ticket.
  const [openId, setOpenId] = useState(params.get("open"));
  const detailRef = useRef(null);
  const searchId = useId();
  const statusId = useId();

  const refresh = useCallback(() => {
    api
      .managerTickets({ q: query.trim(), status })
      .then((d) => {
        setData(d);
        setError("");
      })
      .catch((err) => setError(err.message));
  }, [query, status]);

  useEffect(() => {
    const timer = setTimeout(refresh, 250);
    return () => clearTimeout(timer);
  }, [refresh]);

  function open(ticketId) {
    setOpenId(ticketId);
    requestAnimationFrame(() => detailRef.current?.scrollIntoView({ behavior: "smooth", block: "start" }));
  }

  if (error) return <p className="error">{error}</p>;
  if (!data) return <p className="hint">Loading tickets…</p>;
  if (!data.department)
    return <p className="empty-state">You don't have a department yet. Ask your administrator to assign one.</p>;
  const tickets = data.tickets;
  const technicians = data.technicians;

  const visible = tickets;

  return (
    <div className="admin-tickets">
      <div className="list-filters">
        <label className="sr-only" htmlFor={searchId}>
          Search tickets
        </label>
        <input
          id={searchId}
          type="search"
          className="table-search"
          placeholder="Search ticket #, subject, customer"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
        <label className="inline-select" htmlFor={statusId}>
          <span>Status</span>
          <select id={statusId} value={status} onChange={(e) => setStatus(e.target.value)}>
            <option value="">Any</option>
            {STATUS_KEYS.map((key) => (
              <option key={key} value={key}>
                {statusLabel(key)}
              </option>
            ))}
          </select>
        </label>
        <span className="hint">
          {visible.length} ticket{visible.length === 1 ? "" : "s"} in {data.department.name}
          {technicians.length === 0 && " · no technicians work this department yet, so nothing can be reassigned"}
        </span>
      </div>

      <div className="table-wrap">
        <table className="tickets-table">
          <thead>
            <tr>
              <th>Ticket</th>
              <th>Customer</th>
              <th>Category</th>
              <th>AI route</th>
              <th>Status</th>
              <th>Priority</th>
              <th>SLA</th>
              <th>Technician</th>
              <th>Created</th>
              <th>
                <span className="sr-only">Open</span>
              </th>
            </tr>
          </thead>
          <tbody>
            {visible.map((t) => (
              <tr key={t.ticket_id} className={openId === t.ticket_id ? "is-selected" : ""}>
                <td className="ticket-cell">
                  <span className="ticket-cell-id">
                    <span className="mono">{t.ticket_id}</span>
                    {t.ticket_type === "chat" && <ChatBadge />}
                  </span>
                  <span className="ticket-cell-subject" title={subjectOf(t)}>
                    {subjectOf(t)}
                  </span>
                </td>
                <td className="customer-cell">
                  <span>{t.customer_name}</span>
                  <span className="hint">{t.customer_email}</span>
                </td>
                <td>{categoryLabel(t.category)}</td>
                <td>
                  <span className="route-cell">
                    <RouteChip route={t.route} />
                    <ConfidenceChip confidence={t.confidence} />
                  </span>
                </td>
                <td>
                  <StatusChip status={t.status} />
                </td>
                <td>
                  <PriorityCell ticket={t} onChanged={refresh} />
                </td>
                <td>{t.sla ? <SlaChip sla={t.sla} compact /> : <span className="hint">—</span>}</td>
                <td>
                  <TechnicianAssignCell ticket={t} technicians={technicians} onReassigned={refresh} />
                </td>
                <td>
                  <time dateTime={t.created_at} title={absoluteTime(t.created_at)}>
                    {relativeTime(t.created_at)}
                  </time>
                </td>
                <td>
                  <button
                    type="button"
                    aria-expanded={openId === t.ticket_id}
                    onClick={() => (openId === t.ticket_id ? setOpenId(null) : open(t.ticket_id))}
                  >
                    {openId === t.ticket_id ? "Close" : "Open"}
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div ref={detailRef} className="admin-ticket-detail">
        {openId && (
          <div className="card">
            <StaffTicketView key={openId} ticketId={openId} />
          </div>
        )}
      </div>
    </div>
  );
}

// Older tickets have no subject: fall back to the first line of the text.
function subjectOf(ticket) {
  if (ticket.subject) return ticket.subject;
  return parseTicketText(ticket.ticket_text).original.split("\n")[0];
}

