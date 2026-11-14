import { useEffect, useId, useState } from "react";
import { Link } from "react-router-dom";
import { CircleAlert, Check } from "lucide-react";
import { api } from "@/api";
import { cn } from "@/lib/utils";
import { Alert } from "@/ui/alert";
import { Button } from "@/ui/button";
import { Input, Select } from "@/ui/input";
import { Skeleton } from "@/ui/skeleton";
import { MANAGER_TYPES } from "@/lib/managerTypes";
import { categoryLabel } from "@/utils/categories";
import { setProduct } from "@/utils/product";
import { SunriseBanner } from "@/components/illustrations";
import { BOT_NAME } from "@/lib/people";

/* First-run setup for the admin, at /admin/settings: the product profile
 * (what Settings -> Product stores), a look at the categories and which
 * department owns each, a department for every support engineer (a manager
 * can only hand tickets to technicians in their department), then each
 * manager's department and type (a Platform Lead needs none). Everything
 * is saved through the same admin endpoints as Settings and Users, and
 * can be changed there later. */

const STEPS = ["Product", "Categories", "Support engineers' departments", "Managers", "Done"];

function StepList({ current }) {
  return (
    <ol className="m-0 flex list-none flex-col gap-1 p-0 max-md:flex-row max-md:flex-wrap max-md:gap-x-4">
      {STEPS.map((label, i) => {
        const done = i < current;
        const now = i === current;
        return (
          <li
            key={label}
            aria-current={now ? "step" : undefined}
            className={cn("flex items-center gap-2.5 py-1.5 text-sm", now ? "font-bold text-fg" : "text-muted-fg")}
          >
            <span
              aria-hidden="true"
              className={cn(
                "inline-flex size-8 shrink-0 items-center justify-center rounded-full border text-sm font-bold tabular-nums",
                now && "border-primary bg-primary text-primary-fg",
                done && "border-transparent",
                !now && !done && "border-border-strong",
              )}
              style={done ? { background: "var(--status-resolved-bg)", color: "var(--status-resolved-fg)" } : undefined}
            >
              {done ? <Check className="size-3.5" strokeWidth={2.5} /> : i + 1}
            </span>
            <span className="max-md:sr-only">{label}</span>
          </li>
        );
      })}
    </ol>
  );
}

function Field({ label, hint, children, id }) {
  return (
    <div className="flex flex-col gap-1.5">
      <label htmlFor={id} className="text-sm font-medium">
        {label}
      </label>
      {children}
      {hint && <p className="m-0 text-sm text-muted-fg">{hint}</p>}
    </div>
  );
}

function ProductStep({ initial, onSaved }) {
  const [value, setValue] = useState(initial);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const ids = { name: useId(), description: useId(), team: useId() };

  async function save(e) {
    e.preventDefault();
    setSaving(true);
    setError("");
    try {
      const saved = await api.adminSaveSettings("product", value);
      const product = saved.sections?.product || value;
      setProduct(product);
      onSaved(product);
    } catch (err) {
      setError(err.message);
    } finally {
      setSaving(false);
    }
  }

  return (
    <form onSubmit={save} className="flex max-w-[34rem] flex-col gap-4">
      <div>
        <h2 className="m-0 text-xl">The product you support</h2>
        <p className="m-0 mt-1 text-muted-fg">
          {BOT_NAME} names it in replies and uses the description to understand questions.
        </p>
      </div>
      <Field id={ids.name} label="Product name" hint="Leave it empty until it is known: replies then say “the product”.">
        <Input id={ids.name} maxLength={80} value={value.name} onChange={(e) => setValue({ ...value, name: e.target.value })} />
      </Field>
      <Field id={ids.description} label="One-line description" hint="For example: an HR management system.">
        <Input
          id={ids.description}
          maxLength={200}
          value={value.description}
          onChange={(e) => setValue({ ...value, description: e.target.value })}
        />
      </Field>
      <Field id={ids.team} label="Support team name" hint="Signs the email replies and names the team in messages.">
        <Input
          id={ids.team}
          maxLength={80}
          required
          value={value.support_team_name}
          onChange={(e) => setValue({ ...value, support_team_name: e.target.value })}
        />
      </Field>
      {error && <Alert tone="negative">{error}</Alert>}
      <div>
        <Button type="submit" size="lg" disabled={saving}>
          {saving ? "Saving…" : "Save and continue"}
        </Button>
      </div>
    </form>
  );
}

function CategoriesStep({ departments, categories, onNext, onBack }) {
  const owner = {};
  for (const d of departments) for (const c of d.categories) owner[c] = d.name;
  const unowned = categories.filter((c) => !owner[c]);
  return (
    <div className="flex max-w-[40rem] flex-col gap-4">
      <div>
        <h2 className="m-0 text-xl">Categories and who handles them</h2>
        <p className="m-0 mt-1 text-muted-fg">
          Every ticket gets one of these categories, and the department that owns it sees the ticket. Managers add or
          rename categories under Knowledge base; you move them between departments under{" "}
          <Link to="/admin/departments">Departments</Link>.
        </p>
      </div>
      {unowned.length > 0 && (
        <Alert tone="warning" title={`${unowned.length} ${unowned.length === 1 ? "category has" : "categories have"} no department`}>
          Tickets in them reach no manager until a department owns them.
        </Alert>
      )}
      <ul className="m-0 list-none divide-y divide-border border-y border-border p-0">
        {categories.map((c) => (
          <li key={c} className="flex items-center justify-between gap-4 py-2.5">
            <span>{categoryLabel(c)}</span>
            <span className={cn("text-sm", owner[c] ? "text-muted-fg" : "font-medium text-warning")}>
              {owner[c] || "No department"}
            </span>
          </li>
        ))}
      </ul>
      <div className="flex gap-3">
        <Button variant="outline" size="lg" onClick={onBack}>
          Back
        </Button>
        <Button size="lg" onClick={onNext}>
          Continue
        </Button>
      </div>
    </div>
  );
}

function TechniciansStep({ departments, onNext, onBack }) {
  const [technicians, setTechnicians] = useState(null);
  const [saving, setSaving] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    api
      .adminUsers({ role: "technician", status: "active" })
      .then((rows) => setTechnicians(Array.isArray(rows) ? rows : rows.users || []))
      .catch((err) => setError(err.message));
  }, []);

  async function assign(tech, departmentId) {
    setSaving(tech.user_id);
    setError("");
    try {
      await api.adminUpdateUser(tech.user_id, { department_id: departmentId || null });
      const name = departments.find((d) => d.department_id === departmentId)?.name || null;
      setTechnicians((list) =>
        list.map((t) => (t.user_id === tech.user_id ? { ...t, department_id: departmentId || null, department_name: name } : t)),
      );
    } catch (err) {
      setError(err.message);
    } finally {
      setSaving("");
    }
  }

  const missing = technicians ? technicians.filter((t) => !t.department_id).length : 0;
  return (
    <div className="flex max-w-[40rem] flex-col gap-4">
      <div>
        <h2 className="m-0 text-xl">Give each support engineer a department</h2>
        <p className="m-0 mt-1 text-muted-fg">A manager can only hand tickets to support engineers in their department.</p>
      </div>
      {technicians && (
        <p className={cn("m-0 flex items-center gap-2 font-medium", missing ? "text-warning" : "text-positive")} role="status">
          {missing ? <CircleAlert aria-hidden="true" className="size-4" /> : <Check aria-hidden="true" className="size-4" />}
          {missing === 0
            ? "Every support engineer has a department."
            : `${missing} of ${technicians.length} support engineer${technicians.length === 1 ? "" : "s"} still ${missing === 1 ? "has" : "have"} no department.`}
        </p>
      )}
      {error && <Alert tone="negative">{error}</Alert>}
      {!technicians && !error && <Skeleton className="h-24" />}
      {technicians && technicians.length === 0 && (
        <p className="m-0 text-muted-fg">
          No support engineers yet. Add them under <Link to="/admin">Users</Link>; you can come back here any time.
        </p>
      )}
      {technicians && technicians.length > 0 && (
        <ul className="m-0 list-none divide-y divide-border border-y border-border p-0">
          {technicians.map((t) => (
            <li key={t.user_id} className="flex flex-wrap items-center gap-3 py-2.5">
              <span className="min-w-0 flex-1">
                <span className="block truncate">{t.name}</span>
                <span className="block truncate text-sm text-muted-fg">{t.email}</span>
              </span>
              <Select
                aria-label={`Department for ${t.name}`}
                value={t.department_id || ""}
                disabled={saving === t.user_id}
                onChange={(e) => assign(t, e.target.value)}
                className={cn("w-56", !t.department_id && "border-warning")}
              >
                <option value="">No department</option>
                {departments.map((d) => (
                  <option key={d.department_id} value={d.department_id}>
                    {d.name}
                  </option>
                ))}
              </Select>
            </li>
          ))}
        </ul>
      )}
      <div className="flex gap-3">
        <Button variant="outline" size="lg" onClick={onBack}>
          Back
        </Button>
        <Button size="lg" onClick={onNext}>
          {missing ? "Continue anyway" : "Continue"}
        </Button>
      </div>
    </div>
  );
}

function ManagersStep({ departments, onNext, onBack }) {
  const [managers, setManagers] = useState(null);
  const [saving, setSaving] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    api
      .adminUsers({ role: "manager", status: "active" })
      .then((rows) => setManagers(Array.isArray(rows) ? rows : rows.users || []))
      .catch((err) => setError(err.message));
  }, []);

  async function save(manager, changes) {
    setSaving(manager.user_id);
    setError("");
    try {
      const saved = await api.adminUpdateUser(manager.user_id, changes);
      setManagers((list) => list.map((m) => (m.user_id === manager.user_id ? { ...m, ...saved } : m)));
    } catch (err) {
      setError(err.message);
    } finally {
      setSaving("");
    }
  }

  // A Platform Lead sees every department, so only the others need one.
  const missing = managers ? managers.filter((m) => !m.department_id && m.manager_type !== "platform_lead").length : 0;
  return (
    <div className="flex max-w-[44rem] flex-col gap-4">
      <div>
        <h2 className="m-0 text-xl">Managers: department and type</h2>
        <p className="m-0 mt-1 text-muted-fg">
          Tech Leads, Product Managers and Incident Managers see their own department. A Platform Lead sees every
          department and doesn't need one.
        </p>
      </div>
      {managers && (
        <p className={cn("m-0 flex items-center gap-2 font-medium", missing ? "text-warning" : "text-positive")} role="status">
          {missing ? <CircleAlert aria-hidden="true" className="size-4" /> : <Check aria-hidden="true" className="size-4" />}
          {missing === 0
            ? "Every manager who needs a department has one."
            : `${missing} manager${missing === 1 ? " still has" : "s still have"} no department.`}
        </p>
      )}
      {error && <Alert tone="negative">{error}</Alert>}
      {!managers && !error && <Skeleton className="h-24" />}
      {managers && managers.length === 0 && (
        <p className="m-0 text-muted-fg">
          No managers yet. Add them under <Link to="/admin">Users</Link>; you can come back here any time.
        </p>
      )}
      {managers && managers.length > 0 && (
        <ul className="m-0 list-none divide-y divide-border border-y border-border p-0">
          {managers.map((m) => {
            const lead = m.manager_type === "platform_lead";
            return (
              <li key={m.user_id} className="flex flex-wrap items-center gap-3 py-2.5">
                <span className="min-w-0 flex-1 basis-48">
                  <span className="block truncate">{m.name}</span>
                  <span className="block truncate text-sm text-muted-fg">{m.email}</span>
                </span>
                <Select
                  aria-label={`Manager type for ${m.name}`}
                  value={m.manager_type || "tech_lead"}
                  disabled={saving === m.user_id}
                  onChange={(e) => save(m, { manager_type: e.target.value })}
                  className="w-44"
                >
                  {Object.entries(MANAGER_TYPES).map(([key, label]) => (
                    <option key={key} value={key}>
                      {label}
                    </option>
                  ))}
                </Select>
                <Select
                  aria-label={`Department for ${m.name}`}
                  value={m.department_id || ""}
                  disabled={saving === m.user_id}
                  onChange={(e) => save(m, { department_id: e.target.value || null })}
                  className={cn("w-52", !m.department_id && !lead && "border-warning")}
                >
                  <option value="">{lead ? "All departments" : "No department"}</option>
                  {departments.map((d) => (
                    <option key={d.department_id} value={d.department_id}>
                      {d.name}
                    </option>
                  ))}
                </Select>
              </li>
            );
          })}
        </ul>
      )}
      <div className="flex gap-3">
        <Button variant="outline" size="lg" onClick={onBack}>
          Back
        </Button>
        <Button size="lg" onClick={onNext}>
          {missing ? "Continue anyway" : "Continue"}
        </Button>
      </div>
    </div>
  );
}

export default function SetupWizard({ onClose }) {
  const [step, setStep] = useState(0);
  const [product, setProductState] = useState(null);
  const [departments, setDepartments] = useState(null);
  const [error, setError] = useState("");

  useEffect(() => {
    Promise.all([api.adminSettings(), api.adminDepartments()])
      .then(([settings, d]) => {
        setProductState(settings.sections.product);
        setDepartments(d);
      })
      .catch((err) => setError(err.message));
  }, []);

  if (error) return <Alert tone="negative">{error}</Alert>;
  if (!product || !departments) return <Skeleton className="h-64" />;

  return (
    <div className="flex flex-col gap-6">
      <SunriseBanner className="h-24 w-full rounded-card" />
      <div className="flex flex-wrap items-baseline justify-between gap-3">
        <div>
          <h1 className="m-0 text-2xl">Let’s set up your help desk</h1>
          <p className="m-0 mt-1 text-muted-fg">About five minutes. Everything here can be changed later in Settings.</p>
        </div>
        {step < 4 && (
          <Button variant="link" onClick={onClose}>
            Skip for now
          </Button>
        )}
      </div>
      <div className="grid gap-8 rounded-card border border-border bg-sheet p-6 shadow-card md:grid-cols-[15rem_minmax(0,1fr)] md:p-8">
        <StepList current={step} />
        <section aria-live="polite">
          {step === 0 && (
            <ProductStep
              initial={product}
              onSaved={(saved) => {
                setProductState(saved);
                setStep(1);
              }}
            />
          )}
          {step === 1 && (
            <CategoriesStep
              departments={departments.departments}
              categories={departments.categories}
              onBack={() => setStep(0)}
              onNext={() => setStep(2)}
            />
          )}
          {step === 2 && (
            <TechniciansStep departments={departments.departments} onBack={() => setStep(1)} onNext={() => setStep(3)} />
          )}
          {step === 3 && (
            <ManagersStep departments={departments.departments} onBack={() => setStep(2)} onNext={() => setStep(4)} />
          )}
          {step === 4 && (
            <div className="flex max-w-[34rem] flex-col gap-4">
              <h2 className="m-0 text-xl">The help desk is set up</h2>
              <p className="m-0 text-muted-fg">
                {product.name ? `Customers now see “${product.name} support”.` : "The product is still unnamed; replies say “the product”."}{" "}
                Next: add the knowledge base so {BOT_NAME} has guides to answer from (managers do that under
                Knowledge base), and check the SLA targets in Settings.
              </p>
              <div>
                <Button size="lg" onClick={onClose}>
                  Go to Settings
                </Button>
              </div>
            </div>
          )}
        </section>
      </div>
    </div>
  );
}
