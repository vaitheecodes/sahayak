/* Manager: everything limited to the manager's own department (the
 * backend enforces it on every endpoint, backend/manager.py). A Platform
 * Lead sees every department, picks one or all for Dashboard, SLA and
 * Department tickets (lib/managerScope.js), and has Teams.
 *
 *   Overview   Dashboard ("Dashboard · <department>"), SLA
 *   Work       Department tickets (reassign + priority), Chats,
 *              Chat reviews, Incidents, Teams (Platform Lead)
 *   Knowledge base pages live under /kb (pages/KnowledgeBase.jsx). */

import { useState } from "react";
import { Navigate, useParams } from "react-router-dom";
import AppShell from "../layout/AppShell";
import ChatReviews from "../components/ChatReviews";
import DepartmentTickets from "../components/DepartmentTickets";
import IncidentsPanel from "../components/IncidentsPanel";
import SlaPanel from "../components/SlaPanel";
import StaffChats from "../components/StaffChats";
import UnansweredPanel from "../components/UnansweredPanel";
import Dashboard from "../components/dashboard/Dashboard";
import DepartmentPicker from "../components/manager/DepartmentPicker";
import Teams from "../components/manager/Teams";
import { useManagerScope } from "../lib/managerScope";

const SECTIONS = {
  dashboard: "Dashboard",
  sla: "SLA",
  tickets: "Department tickets",
  chats: "Chats",
  "chat-reviews": "Chat reviews",
  incidents: "Incidents",
  teams: "Teams",
  unanswered: "Unanswered questions",
};
// The pages a Platform Lead can narrow to one department.
const PICKS_DEPARTMENT = new Set(["dashboard", "sla", "tickets"]);

export default function ManagerPortal() {
  const { section = "dashboard" } = useParams();
  const [department, setDepartment] = useState(null);
  const scope = useManagerScope();
  if (!SECTIONS[section]) return <Navigate to="/manager" replace />;
  if (section === "teams" && scope.ready && !scope.allowsTeams) return <Navigate to="/manager" replace />;
  const title = section === "dashboard" && department ? `Dashboard · ${department}` : SECTIONS[section];
  const picker =
    scope.canPick && PICKS_DEPARTMENT.has(section) ? (
      <DepartmentPicker value={scope.department} onChange={scope.setDepartment} departments={scope.departments} />
    ) : null;

  return (
    <AppShell role="manager" title={title} actions={picker}>
      <div className="p-4 md:p-6">
        {/* Until /auth/me is in, `department` is undefined: the server's
            default, which for a Platform Lead is every department too. */}
        {section === "dashboard" && (
          <Dashboard role="manager" department={scope.department} onDepartment={setDepartment} />
        )}
        {section === "sla" && <SlaPanel department={scope.department} />}
        {section === "tickets" && (
          <DepartmentTickets department={scope.department} acrossDepartments={scope.canPick} />
        )}
        {section === "teams" && scope.allowsTeams && <Teams />}
        {section === "chats" && <StaffChats />}
        {section === "chat-reviews" && <ChatReviews />}
        {section === "incidents" && <IncidentsPanel />}
        {section === "unanswered" && <UnansweredPanel />}
      </div>
    </AppShell>
  );
}
