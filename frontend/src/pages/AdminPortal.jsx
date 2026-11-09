import { Navigate, useParams } from "react-router-dom";
import AppShell from "../layout/AppShell";
import AuditPanel from "../components/AuditPanel";
import DepartmentsPanel from "../components/DepartmentsPanel";
import SettingsPanel from "../components/SettingsPanel";
import { AdminSlaSettings } from "../components/SlaPanel";
import UsersPanel from "../components/UsersPanel";

/* The admin runs people and the system only: Users and Departments,
 * Settings (including the SLA targets) and the Activity log. Tickets,
 * dashboards and SLA reports are the managers', limited to their
 * department; the backend refuses the admin there too
 * (tests/test_role_scope.py). */

function Settings() {
  return (
    <div className="flex flex-col gap-6">
      <SettingsPanel />
      <AdminSlaSettings />
    </div>
  );
}

const SECTIONS = {
  users: ["Users", UsersPanel],
  departments: ["Departments", DepartmentsPanel],
  settings: ["Settings", Settings],
  activity: ["Activity log", AuditPanel],
};

export default function AdminPortal() {
  const { section = "users" } = useParams();
  if (!SECTIONS[section]) return <Navigate to="/admin" replace />;
  const [title, Panel] = SECTIONS[section];

  return (
    <AppShell role="admin" title={title}>
      <div className="tab-content p-4 md:p-6">
        <Panel />
      </div>
    </AppShell>
  );
}
