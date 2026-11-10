/* Manager: everything limited to the manager's own department (the
 * backend enforces it on every endpoint, backend/manager.py).
 *
 *   Overview   Dashboard ("Dashboard · <department>"), SLA
 *   Work       Department tickets (reassign + priority), Chats,
 *              Chat reviews, Incidents
 *   Knowledge base pages live under /kb (pages/KnowledgeBase.jsx). */

import { useState } from "react";
import { Navigate, useParams } from "react-router-dom";
import AppShell from "../layout/AppShell";
import ChatReviews from "../components/ChatReviews";
import DepartmentTickets from "../components/DepartmentTickets";
import IncidentsPanel from "../components/IncidentsPanel";
import SlaPanel from "../components/SlaPanel";
import StaffChats from "../components/StaffChats";
import Dashboard from "../components/dashboard/Dashboard";

const SECTIONS = {
  dashboard: "Dashboard",
  sla: "SLA",
  tickets: "Department tickets",
  chats: "Chats",
  "chat-reviews": "Chat reviews",
  incidents: "Incidents",
};

export default function ManagerPortal() {
  const { section = "dashboard" } = useParams();
  const [department, setDepartment] = useState(null);
  if (!SECTIONS[section]) return <Navigate to="/manager" replace />;
  const title = section === "dashboard" && department ? `Dashboard · ${department}` : SECTIONS[section];

  return (
    <AppShell role="manager" title={title}>
      <div className="p-4 md:p-6">
        {section === "dashboard" && <Dashboard role="manager" onDepartment={setDepartment} />}
        {section === "sla" && <SlaPanel />}
        {section === "tickets" && <DepartmentTickets />}
        {section === "chats" && <StaffChats />}
        {section === "chat-reviews" && <ChatReviews />}
        {section === "incidents" && <IncidentsPanel />}
      </div>
    </AppShell>
  );
}
