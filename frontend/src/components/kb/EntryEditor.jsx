import { Fragment, useEffect, useId, useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { ArrowLeft, Check, ExternalLink, Plus, Save, Trash2, X } from "lucide-react";
import { api } from "@/api";
import { Alert } from "@/ui/alert";
import { Badge } from "@/ui/badge";
import { Button } from "@/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/ui/card";
import { Input, Select, Textarea } from "@/ui/input";
import { Field } from "@/ui/label";
import { Skeleton } from "@/ui/skeleton";
import { categoryLabel } from "@/utils/categories";
import { ENTRY_TONE, FLAGS, formatDateTime, reasonLabel } from "./format";

/* One entry: its fields on the left, each step beside the passage it is
 * quoted from, and the source section on the right with those passages
 * marked. Drafts can be edited (technicians and managers); managers
 * approve or reject. Every save names the version it was made on. */

function toForm(entry) {
  return {
    title: entry.title,
    category: entry.category,
    kind: entry.kind || "how-to",
    questions: entry.questions.join("\n"),
    answer: entry.answer,
    steps: entry.steps.map((s) => ({ text: s.text, quote: s.quote, support_check: s.support_check })),
    applies_to: entry.applies_to,
  };
}

function changes(form, entry) {
  const out = {};
  const questions = form.questions.split("\n").map((q) => q.trim()).filter(Boolean);
  if (form.title !== entry.title) out.title = form.title;
  if (form.category !== entry.category) out.category = form.category;
  if (form.kind !== (entry.kind || "how-to")) out.kind = form.kind;
  if (JSON.stringify(questions) !== JSON.stringify(entry.questions)) out.questions = questions;
  if (form.answer !== entry.answer) out.answer = form.answer;
  const steps = form.steps.map(({ text, quote }) => ({ text: text.trim(), quote: quote.trim() }));
  if (JSON.stringify(steps) !== JSON.stringify(entry.steps.map(({ text, quote }) => ({ text, quote })))) out.steps = steps;
  if (JSON.stringify([...form.applies_to].sort()) !== JSON.stringify([...entry.applies_to].sort())) {
    out.applies_to = form.applies_to;
  }
  return out;
}

export default function EntryEditor({ entryId, isManager }) {
  const [entry, setEntry] = useState(null);
  const [form, setForm] = useState(null);
  const [categories, setCategories] = useState([]);
  const [terms, setTerms] = useState([]);
  const [note, setNote] = useState("");
  const [acknowledged, setAcknowledged] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState("");
  const navigate = useNavigate();
  const ids = { title: useId(), category: useId(), kind: useId(), questions: useId(), answer: useId(), note: useId() };

  function show(next) {
    setEntry(next);
    setForm(toForm(next));
  }

  useEffect(() => {
    api.kbEntry(entryId).then(show).catch((err) => setError(err.message));
    api.kbCategories().then((d) => setCategories(d.categories.filter((c) => c.status === "confirmed"))).catch(() => {});
    api.kbTerms("all").then((d) => setTerms(d.terms.filter((t) => ["confirmed", "proposed"].includes(t.status)))).catch(() => {});
  }, [entryId]);

  const pending = useMemo(() => (form && entry ? changes(form, entry) : {}), [form, entry]);
  const dirty = Object.keys(pending).length > 0;

  if (error && !entry) return <Alert tone="negative">{error}</Alert>;
  if (!entry || !form) return <Skeleton className="h-96" />;

  const editable = entry.status === "draft";
  const set = (field) => (value) => setForm({ ...form, [field]: value });
  const setStep = (i, field, value) =>
    setForm({ ...form, steps: form.steps.map((s, j) => (j === i ? { ...s, [field]: value, support_check: null } : s)) });

  async function run(kind, fn, done) {
    setBusy(kind);
    setError("");
    setMessage("");
    try {
      const next = await fn();
      show(next);
      setMessage(done);
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy("");
    }
  }

  const save = () => run("save", () => api.kbEditEntry(entryId, { version: entry.version, ...pending }), "Saved.");
  const decide = (decision) =>
    run(decision, () => api.kbDecideEntry(entryId, decision, entry.version, note, acknowledged),
      decision === "approve" ? "Approved: the bot can use this entry now." : "Rejected.");

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center gap-2">
        <Button variant="ghost" size="sm" onClick={() => navigate("/kb/review")}>
          <ArrowLeft aria-hidden="true" />
          Review queue
        </Button>
        <Badge tone={ENTRY_TONE[entry.status]} dot>
          {entry.status}
        </Badge>
        {entry.flags.map((f) => (
          <Badge key={f} tone={FLAGS[f]?.[0]}>
            {f === "incomplete" && entry.completeness
              ? `${FLAGS[f][1]} (${entry.completeness.kept} of ${entry.completeness.expected})`
              : FLAGS[f]?.[1] || f}
          </Badge>
        ))}
        <span className="ml-auto text-sm text-muted-fg">
          Version {entry.version} · updated {formatDateTime(entry.updated_at)}
        </span>
      </div>

      <Notices entry={entry} />
      {error && <Alert tone="negative">{error}</Alert>}
      {message && <Alert tone="positive">{message}</Alert>}

      <div className="grid gap-6 xl:grid-cols-[minmax(0,7fr)_minmax(0,5fr)]">
        <Card>
          <CardHeader>
            <CardTitle>Entry</CardTitle>
          </CardHeader>
          <CardContent>
            <fieldset disabled={!editable} className="m-0 flex min-w-0 flex-col gap-4 border-0 p-0">
              <Field label="Title" htmlFor={ids.title}>
                <Input id={ids.title} value={form.title} maxLength={120} onChange={(e) => set("title")(e.target.value)} />
              </Field>
              <div className="grid gap-4 sm:grid-cols-2">
                <Field label="Category" htmlFor={ids.category}>
                  <Select id={ids.category} value={form.category} onChange={(e) => set("category")(e.target.value)}>
                    {!categories.some((c) => c.name === form.category) && (
                      <option value={form.category}>{categoryLabel(form.category)}</option>
                    )}
                    {categories.map((c) => (
                      <option key={c.name} value={c.name}>
                        {c.label}
                      </option>
                    ))}
                  </Select>
                </Field>
                <Field label="Kind" htmlFor={ids.kind}>
                  <Select id={ids.kind} value={form.kind} onChange={(e) => set("kind")(e.target.value)}>
                    <option value="how-to">How-to (doing a task)</option>
                    <option value="troubleshooting">Troubleshooting (fixing a fault)</option>
                  </Select>
                </Field>
              </div>
              <Field label="Customer questions" htmlFor={ids.questions} hint="One per line. The bot matches customers' messages against these.">
                <Textarea id={ids.questions} rows={4} value={form.questions} onChange={(e) => set("questions")(e.target.value)} />
              </Field>
              <Field label="Answer" htmlFor={ids.answer} hint="In your own words; the steps carry the details.">
                <Textarea id={ids.answer} rows={3} maxLength={1500} value={form.answer} onChange={(e) => set("answer")(e.target.value)} />
              </Field>
              <Steps form={form} setForm={setForm} setStep={setStep} editable={editable} />
              <AppliesTo value={form.applies_to} terms={terms} onChange={set("applies_to")} />
            </fieldset>

            <div className="mt-6 flex flex-col gap-3 border-t border-rule pt-4">
              {editable && isManager && entry.completeness && (
                <label className="flex items-start gap-2 text-base">
                  <input
                    type="checkbox"
                    className="mt-1 size-4"
                    checked={acknowledged}
                    onChange={(e) => setAcknowledged(e.target.checked)}
                  />
                  <span>
                    I checked the page: the {entry.completeness.expected - entry.completeness.kept} missing step(s) of
                    its list aren't needed for this entry.
                  </span>
                </label>
              )}
              {editable && isManager && (
                <Field label="Review note (optional)" htmlFor={ids.note}>
                  <Input id={ids.note} value={note} maxLength={500} onChange={(e) => setNote(e.target.value)} />
                </Field>
              )}
              {editable ? (
                <div className="flex flex-wrap gap-2">
                  {isManager && (
                    <Button
                      onClick={() => decide("approve")}
                      disabled={!!busy || dirty || (entry.completeness && !acknowledged)}
                      title={dirty ? "Save your changes first" : undefined}
                    >
                      <Check aria-hidden="true" />
                      {busy === "approve" ? "Approving…" : "Approve"}
                    </Button>
                  )}
                  <Button variant={isManager ? "outline" : "default"} onClick={save} disabled={!!busy || !dirty}>
                    <Save aria-hidden="true" />
                    {busy === "save" ? "Saving…" : "Save changes"}
                  </Button>
                  {isManager && (
                    <Button variant="outline" onClick={() => decide("reject")} disabled={!!busy}>
                      <X aria-hidden="true" />
                      {busy === "reject" ? "Rejecting…" : "Reject"}
                    </Button>
                  )}
                  {!isManager && <p className="m-0 self-center text-sm text-muted-fg">A manager approves or rejects drafts.</p>}
                </div>
              ) : (
                <p className="m-0 text-sm text-muted-fg">
                  {entry.status === "approved" ? "Approved" : "Decided"} by {entry.reviewed_by_name || "—"} on{" "}
                  {formatDateTime(entry.reviewed_at)}
                  {entry.review_note ? `: “${entry.review_note}”` : "."}
                </p>
              )}
            </div>
          </CardContent>
        </Card>

        <SourceSection entry={entry} steps={form.steps} />
      </div>
    </div>
  );
}

function Notices({ entry }) {
  const notes = entry.notes || {};
  const signals = [...(notes.chunk_signals || []), ...(notes.output_signals || [])];
  return (
    <>
      {entry.completeness && (
        <Alert
          tone="warning"
          title={`Possibly incomplete: ${entry.completeness.kept} of ${entry.completeness.expected} steps of the page's numbered list`}
        >
          Steps whose rewrite the check couldn't confirm were dropped. Add them back from the source section (each
          with its item as the quote), or confirm below that they aren't needed.
        </Alert>
      )}
      {entry.duplicate && (
        <Alert tone="warning" title={`Possible duplicate of ${entry.duplicate.kb_entry_id} (similarity ${entry.duplicate.score})`}>
          <Link to={`/kb/review/${entry.duplicate.kb_entry_id}`} className="underline underline-offset-4">
            {entry.duplicate.title}
          </Link>{" "}
          ({entry.duplicate.status}). Reject this one if it says the same thing.
        </Alert>
      )}
      {signals.length > 0 && (
        <Alert tone="negative" title="The source contains text aimed at the AI or at reviewers">
          Signals: {[...new Set(signals)].map((s) => s.replace(/_/g, " ")).join(", ")}. The AI was told to ignore it;
          check every field and step against the page before approving.
        </Alert>
      )}
      {entry.stale && (
        <Alert tone="warning" title="The source page changed">This entry's section is no longer on the page.</Alert>
      )}
      {(notes.removed || []).length > 0 && (
        <Alert tone="info" title="The drafted answer was removed">
          {notes.removed.map(reasonLabel).join(", ")}. Write a short answer in your own words.
        </Alert>
      )}
    </>
  );
}

const SUPPORT = { supported: ["positive", "AI check: supported"] };

function Steps({ form, setForm, setStep, editable }) {
  const remove = (i) => setForm({ ...form, steps: form.steps.filter((_, j) => j !== i) });
  const add = () => setForm({ ...form, steps: [...form.steps, { text: "", quote: "", support_check: null }] });
  return (
    <div className="flex flex-col gap-2">
      <div className="flex items-center justify-between">
        <span className="text-sm font-medium">Steps</span>
        <span className="text-sm text-muted-fg">Each step must quote a passage of the source section.</span>
      </div>
      {form.steps.length === 0 && <p className="m-0 text-sm text-muted-fg">No steps.</p>}
      <ol className="m-0 flex list-none flex-col gap-3 p-0">
        {form.steps.map((step, i) => (
          <li key={i} className="grid gap-2 rounded-md border border-rule p-3 md:grid-cols-2">
            <div className="flex flex-col gap-1.5">
              <label className="text-sm text-muted-fg" htmlFor={`step-${i}`}>
                Step {i + 1}
              </label>
              <Textarea id={`step-${i}`} rows={2} value={step.text} onChange={(e) => setStep(i, "text", e.target.value)} />
            </div>
            <div className="flex flex-col gap-1.5">
              <div className="flex items-center justify-between gap-2">
                <label className="text-sm text-muted-fg" htmlFor={`quote-${i}`}>
                  Quoted passage
                </label>
                {step.support_check ? (
                  <Badge tone={SUPPORT[step.support_check]?.[0] || "neutral"}>{SUPPORT[step.support_check]?.[1] || step.support_check}</Badge>
                ) : (
                  <Badge tone="outline">Not checked by AI</Badge>
                )}
              </div>
              <Textarea
                id={`quote-${i}`}
                rows={2}
                className="border-l-2 border-l-pill-info-fg bg-raised font-mono text-sm"
                value={step.quote}
                onChange={(e) => setStep(i, "quote", e.target.value)}
              />
            </div>
            {editable && (
              <div className="md:col-span-2">
                <Button variant="ghost" size="sm" onClick={() => remove(i)}>
                  <Trash2 aria-hidden="true" />
                  Remove step
                </Button>
              </div>
            )}
          </li>
        ))}
      </ol>
      {editable && (
        <div>
          <Button variant="outline" size="sm" onClick={add}>
            <Plus aria-hidden="true" />
            Add step
          </Button>
        </div>
      )}
    </div>
  );
}

function AppliesTo({ value, terms, onChange }) {
  const toggle = (label) => onChange(value.includes(label) ? value.filter((v) => v !== label) : [...value, label]);
  return (
    <div className="flex flex-col gap-1.5">
      <span className="text-sm font-medium">Applies only to</span>
      {terms.length === 0 ? (
        <p className="m-0 text-sm text-muted-fg">No product terms yet: the entry applies everywhere.</p>
      ) : (
        <div className="flex flex-wrap gap-2">
          {terms.map((t) => (
            <label key={t.term_id} className="inline-flex items-center gap-1.5 rounded-full border border-border px-2.5 py-0.5 text-sm">
              <input type="checkbox" className="size-3.5" checked={value.includes(t.label)} onChange={() => toggle(t.label)} />
              {t.label}
              {t.status === "proposed" && <span className="text-muted-fg">(proposed)</span>}
            </label>
          ))}
        </div>
      )}
      <p className="m-0 text-sm text-muted-fg">Leave all unticked when it applies everywhere. Approval needs confirmed terms.</p>
    </div>
  );
}

function escapeRegExp(text) {
  return text.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

/* The section text with each step's quote marked (whitespace and case
 * insensitive, like the server's check). */
function marked(text, steps) {
  const spans = [];
  steps.forEach((s, i) => {
    const words = (s.quote || "").trim().split(/\s+/).filter(Boolean).map(escapeRegExp);
    if (words.length < 2) return;
    const match = new RegExp(words.join("[\\s*_`]+"), "i").exec(text);
    if (match) spans.push([match.index, match.index + match[0].length, i + 1]);
  });
  spans.sort((a, b) => a[0] - b[0]);
  const out = [];
  let at = 0;
  for (const [start, end, n] of spans) {
    if (start < at) continue;
    out.push(<Fragment key={`t${at}`}>{text.slice(at, start)}</Fragment>);
    out.push(
      <mark key={`m${start}`} className="rounded-sm bg-pill-info px-0.5 text-pill-info-fg" title={`Step ${n}`}>
        {text.slice(start, end)}
        <sup className="ml-0.5 font-sans text-xs">{n}</sup>
      </mark>,
    );
    at = end;
  }
  out.push(<Fragment key="end">{text.slice(at)}</Fragment>);
  return out;
}

function SourceSection({ entry, steps }) {
  const chunk = entry.chunk;
  return (
    <Card className="self-start xl:sticky xl:top-4">
      <CardHeader>
        <div className="min-w-0">
          <CardTitle>Source section</CardTitle>
          <CardDescription>{chunk?.heading_path || "—"}</CardDescription>
        </div>
        {entry.source_url && (
          <a href={entry.source_url} target="_blank" rel="noreferrer noopener" className="inline-flex shrink-0 items-center gap-1 text-sm text-primary hover:underline">
            Open page <ExternalLink className="size-3.5" aria-hidden="true" />
          </a>
        )}
      </CardHeader>
      <CardContent>
        {entry.source && (
          <p className="mt-0 mb-3 text-sm text-muted-fg">
            {entry.source.name}
            {entry.source.kind === "file" && entry.source.filename && ` (file ${entry.source.filename})`}
            {entry.source.kind === "text" && " (pasted text)"}: confirmed public by {entry.source.public_confirmed_by_name} on{" "}
            {formatDateTime(entry.source.public_confirmed_at)}
          </p>
        )}
        {entry.source_licence && (
          <p className="mt-0 mb-3 text-sm text-muted-fg">Licence: {entry.source_licence} (keep the source link)</p>
        )}
        {chunk?.text ? (
          <pre className="m-0 max-h-[70vh] overflow-auto whitespace-pre-wrap break-words rounded-md bg-raised p-3 font-mono text-sm leading-relaxed">
            {marked(chunk.text, steps)}
          </pre>
        ) : (
          <p className="m-0 text-sm text-muted-fg">
            {chunk
              ? `The section text was removed on ${formatDateTime(chunk.purged_at)} (it is kept only until its drafts are decided). The quotes on the steps remain.`
              : "This entry wasn't drafted from a source."}
          </p>
        )}
      </CardContent>
    </Card>
  );
}
