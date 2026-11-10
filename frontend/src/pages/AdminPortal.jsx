import { useEffect, useState } from "react";
import { Navigate, useParams } from "react-router-dom";
import { api } from "@/api";
import SetupWizard from "@/components/SetupWizard";
import { Button } from "@/ui/button";
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

const SETUP_SKIPPED = "setupSkipped";

function skipped() {
  try {
    return localStorage.getItem(SETUP_SKIPPED) === "1";
  } catch {
    return false;
  }
}

/* Settings opens on the first-run setup while the product has no name
 * (unless the admin skipped it in this browser); "Run setup again" brings
 * it back any time. */
function Settings() {
  const [setup, setSetup] = useState(null);

  useEffect(() => {
    api
      .adminSettings()
      .then((s) => setSetup(!s.sections.product.name && !skipped()))
      .catch(() => setSetup(false));
  }, []);

  function close() {
    try {
      localStorage.setItem(SETUP_SKIPPED, "1");
    } catch {
      /* not remembered */
    }
    setSetup(false);
  }

  if (setup === null) return null;
  if (setup) return <SetupWizard onClose={close} />;
  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-border px-4 py-3">
        <p className="m-0 text-muted-fg">
          Setup walks through the product, the categories and each support engineer&apos;s department.
        </p>
        <Button variant="outline" onClick={() => setSetup(true)}>
          Run setup again
        </Button>
      </div>
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
