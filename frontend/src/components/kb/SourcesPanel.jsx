import { useCallback, useEffect, useId, useState } from "react";
import { Link } from "react-router-dom";
import { Calculator, Globe, Play, Plus } from "lucide-react";
import { api } from "@/api";
import { Alert } from "@/ui/alert";
import { Badge } from "@/ui/badge";
import { Button } from "@/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/ui/card";
import { EmptyState } from "@/ui/empty-state";
import { Input } from "@/ui/input";
import { Field } from "@/ui/label";
import { Skeleton } from "@/ui/skeleton";
import { formatDateTime, reasonLabel, RUN_TONE } from "./format";

/* Sources: add a public page (with the "content is public / allowed"
 * confirmation), estimate a run (fetch + chunk, no model calls), then
 * start it. A running run is polled until it finishes. */

export default function SourcesPanel({ isManager }) {
  const [data, setData] = useState(null);
  const [error, setError] = useState("");

  const load = useCallback(() => {
    api
      .kbSources()
      .then(setData)
      .catch((err) => setError(err.message));
  }, []);
  useEffect(load, [load]);

  if (error) return <Alert tone="negative">{error}</Alert>;
  if (!data) return <Skeleton className="h-40" />;

  return (
    <div className="flex flex-col gap-6">
      <CapsLine caps={data.caps} />
      {isManager && <AddSource onAdded={load} />}
      {data.sources.length === 0 ? (
        <Card>
          <EmptyState icon={Globe} title="No sources yet">
            {isManager
              ? "Add a public help page above to draft the first entries."
              : "A manager adds the pages the knowledge base is drafted from."}
          </EmptyState>
        </Card>
      ) : (
        data.sources.map((s) => <SourceCard key={s.source_id} source={s} isManager={isManager} onChange={load} />)
      )}
    </div>
  );
}

function CapsLine({ caps }) {
  return (
    <p className="text-sm text-muted-fg">
      Model-call caps: <span className="tabular-nums text-fg">{caps.per_run}</span> per run,{" "}
      <span className="tabular-nums text-fg">{caps.left_today}</span> of{" "}
      <span className="tabular-nums">{caps.per_day}</span> left today (UTC). Each section of a page costs up to{" "}
      {caps.calls_per_chunk} calls: one to draft, one to check the steps.
    </p>
  );
}

function AddSource({ onAdded }) {
  const [name, setName] = useState("");
  const [url, setUrl] = useState("");
  const [confirmed, setConfirmed] = useState(false);
  const [licence, setLicence] = useState("");
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);
  const ids = { name: useId(), url: useId(), confirm: useId(), licence: useId() };

  async function submit(e) {
    e.preventDefault();
    setSaving(true);
    setError("");
    try {
      await api.kbCreateSource({
        name: name.trim(),
        url: url.trim(),
        public_confirmed: confirmed,
        licence_note: licence.trim(),
      });
      setName("");
      setUrl("");
      setLicence("");
      setConfirmed(false);
      onAdded();
    } catch (err) {
      setError(err.message);
    } finally {
      setSaving(false);
    }
  }

  return (
    <Card>
      <CardHeader>
        <div>
          <CardTitle>Add a source</CardTitle>
          <CardDescription>One public page. Its sections are drafted into entries for review.</CardDescription>
        </div>
      </CardHeader>
      <CardContent>
        <form className="flex flex-col gap-4" onSubmit={submit}>
          <div className="grid gap-4 sm:grid-cols-[minmax(0,1fr)_minmax(0,2fr)]">
            <Field label="Name" htmlFor={ids.name}>
              <Input id={ids.name} value={name} maxLength={120} onChange={(e) => setName(e.target.value)} required />
            </Field>
            <Field label="Page URL" htmlFor={ids.url} hint="http or https on the standard port; private addresses are refused.">
              <Input
                id={ids.url}
                type="url"
                placeholder="https://help.example.com/guide"
                value={url}
                onChange={(e) => setUrl(e.target.value)}
                required
              />
            </Field>
          </div>
          <Field
            label="Licence or attribution (optional)"
            htmlFor={ids.licence}
            hint="For example: CC BY-SA 4.0, Example S.A. It is kept on every entry drafted from this source."
          >
            <Input id={ids.licence} value={licence} maxLength={200} onChange={(e) => setLicence(e.target.value)} />
          </Field>
          <label htmlFor={ids.confirm} className="flex items-start gap-2 text-base">
            <input
              id={ids.confirm}
              type="checkbox"
              className="mt-1 size-4 accent-[var(--color-primary)]"
              checked={confirmed}
              onChange={(e) => setConfirmed(e.target.checked)}
            />
            <span>
              I confirm this content is public, or that we are allowed to use it. My name and the time are saved
              with the source.
            </span>
          </label>
          <div>
            <Button type="submit" disabled={saving || !confirmed || !name.trim() || !url.trim()}>
              <Plus aria-hidden="true" />
              {saving ? "Adding…" : "Add source"}
            </Button>
          </div>
          {error && <Alert tone="negative">{error}</Alert>}
        </form>
      </CardContent>
    </Card>
  );
}

function SourceCard({ source, isManager, onChange }) {
  const [run, setRun] = useState(source.last_run);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");

  // Poll a run that is queued or running.
  useEffect(() => {
    if (!run || !["queued", "running"].includes(run.status)) return undefined;
    const timer = setInterval(() => {
      api
        .kbRun(run.run_id)
        .then((next) => {
          setRun(next);
          if (!["queued", "running"].includes(next.status)) onChange();
        })
        .catch(() => {});
    }, 2000);
    return () => clearInterval(timer);
  }, [run, onChange]);

  async function act(kind, fn) {
    setBusy(kind);
    setError("");
    try {
      setRun(await fn());
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy("");
    }
  }

  const estimate = () => act("estimate", () => api.kbEstimate(source.source_id));
  const start = () => act("start", () => api.kbStartRun(run.run_id, run.estimated_model_calls));
  const counts = source.entries || {};

  return (
    <Card>
      <CardHeader>
        <div className="min-w-0">
          <CardTitle>{source.name}</CardTitle>
          <CardDescription>
            <a href={source.root_url} target="_blank" rel="noreferrer noopener" className="break-all text-primary underline-offset-4 hover:underline">
              {source.root_url}
            </a>
          </CardDescription>
          <p className="mt-1 text-sm text-muted-fg">
            Confirmed public by {source.public_confirmed_by_name} on {formatDateTime(source.public_confirmed_at)}
            {source.licence_note && ` · Licence: ${source.licence_note}`}
          </p>
        </div>
        <div className="flex shrink-0 flex-wrap items-center gap-2">
          <Link to="/kb/review" className="text-sm text-muted-fg hover:text-fg">
            {counts.draft || 0} draft · {counts.approved || 0} approved
          </Link>
          {isManager && (
            <Button variant="outline" onClick={estimate} disabled={!!busy || ["queued", "running"].includes(run?.status)}>
              <Calculator aria-hidden="true" />
              {busy === "estimate" ? "Reading the page…" : "Estimate a run"}
            </Button>
          )}
        </div>
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        {error && <Alert tone="negative">{error}</Alert>}
        {run ? <RunPanel run={run} isManager={isManager} onStart={start} starting={busy === "start"} /> : (
          <p className="text-sm text-muted-fg">No runs yet.</p>
        )}
      </CardContent>
    </Card>
  );
}

function Stat({ label, value }) {
  return (
    <div className="flex flex-col">
      <dt className="text-sm text-muted-fg">{label}</dt>
      <dd className="m-0 text-lg font-medium tabular-nums">{value}</dd>
    </div>
  );
}

function RunPanel({ run, isManager, onStart, starting }) {
  const est = run.estimate || {};
  const caps = est.caps || {};
  const errors = Object.entries(run.errors || {});
  const willCap = run.status === "estimated" && caps.per_run != null &&
    run.estimated_model_calls > Math.min(caps.per_run, caps.left_today);

  return (
    <div className="flex flex-col gap-3 rounded-md border border-rule p-4">
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-medium">Run {run.run_id}</span>
        <Badge tone={RUN_TONE[run.status] || "neutral"} dot>
          {run.status}
        </Badge>
        {run.stop_reason && <span className="text-sm text-muted-fg">{reasonLabel(run.stop_reason)}</span>}
        <span className="ml-auto text-sm text-muted-fg">{formatDateTime(run.finished_at || run.created_at)}</span>
      </div>

      {run.status === "estimated" && (
        <Alert
          tone={willCap ? "warning" : "info"}
          title={`${est.pages} page × ${est.chunks_to_draft} section${est.chunks_to_draft === 1 ? "" : "s"} to draft = up to ${run.estimated_model_calls} model calls`}
          action={
            isManager && (
              <Button onClick={onStart} disabled={starting}>
                <Play aria-hidden="true" />
                {starting ? "Starting…" : "Start run"}
              </Button>
            )
          }
        >
          {est.chunks_unchanged > 0 && <p className="m-0">{est.chunks_unchanged} section(s) unchanged since the last run are skipped.</p>}
          <p className="m-0">
            Caps: {caps.per_run} per run, {caps.left_today} left today.
            {willCap && " The run will stop cleanly at the cap; the next run picks up where it stopped."}
          </p>
        </Alert>
      )}

      {run.status !== "estimated" && (
        <dl className="m-0 grid grid-cols-3 gap-4 sm:grid-cols-6">
          <Stat label="Pages" value={run.pages_fetched} />
          <Stat label="Unchanged" value={run.pages_unchanged} />
          <Stat label="Sections" value={`${run.chunks}/${est.chunks_to_draft ?? 0}`} />
          <Stat label="Drafts" value={run.drafts_created} />
          <Stat label="Steps dropped" value={run.steps_rejected} />
          <Stat label="Model calls" value={`${run.model_calls}/${run.model_call_cap}`} />
        </dl>
      )}

      {errors.length > 0 && (
        <p className="m-0 text-sm text-muted-fg">
          {errors.map(([code, n]) => `${reasonLabel(code)}: ${n}`).join(" · ")}
        </p>
      )}
    </div>
  );
}
