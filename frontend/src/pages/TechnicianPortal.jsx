/* Technician workspace.
 *
 *   My work   Dashboard (own tickets only), Tickets (tabs, filters, claim,
 *             the ticket workspace), Chats (read-only)
 *   More      Chat reviews; the KB review queue and Try a ticket are their
 *             own pages (/kb/review, /try-a-ticket).
 * Incidents a manager assigned to them stay at /technician/incidents. */

import { Navigate, useParams } from "react-router-dom";
import AppShell from "../layout/AppShell";
import ChatReviews from "../components/ChatReviews";
import IncidentsPanel from "../components/IncidentsPanel";
import StaffChats from "../components/StaffChats";
import TechnicianTickets from "../components/TechnicianTickets";
import Dashboard from "../components/dashboard/Dashboard";

const SECTIONS = {
  dashboard: "Dashboard",
  tickets: "Tickets",
  chats: "Chats",
  "chat-reviews": "Chat reviews",
  incidents: "Assigned incidents",
};

export default function TechnicianPortal() {
  const { section = "dashboard" } = useParams();
  if (!SECTIONS[section]) return <Navigate to="/technician" replace />;

  return (
    <AppShell role="technician" title={SECTIONS[section]}>
      <div className="p-4 md:p-6">
        {section === "dashboard" && <Dashboard role="technician" />}
        {section === "tickets" && <TechnicianTickets />}
        {section === "chats" && <StaffChats />}
        {section === "chat-reviews" && <ChatReviews />}
        {/* Only incidents a manager assigned to this technician. */}
        {section === "incidents" && <IncidentsPanel canRun={false} />}
      </div>
    </AppShell>
  );
}
