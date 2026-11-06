import { useCallback, useEffect, useId, useState } from "react";
import { Check, Merge, Plus, Tags, X } from "lucide-react";
import { api } from "@/api";
import { Alert } from "@/ui/alert";
import { Badge } from "@/ui/badge";
import { Button } from "@/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/ui/card";
import { EmptyState } from "@/ui/empty-state";
import { Input, Select } from "@/ui/input";
import { Field } from "@/ui/label";
import { Skeleton } from "@/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/ui/table";

/* Product terms (modules, variants, platforms, integrations, editions):
 * proposed by the drafter or a technician, confirmed / rejected / merged
 * by a manager. Only confirmed terms affect which guide the bot picks. */

const KINDS = ["module", "variant", "platform", "integration", "edition"];
const TONE = { proposed: "info", confirmed: "positive", rejected: "neutral", merged: "neutral" };

export default function TermsPanel({ isManager }) {
  const [terms, setTerms] = useState(null);
  const [error, setError] = useState("");

  const load = useCallback(() => {
    api
      .kbTerms("all")
      .then((d) => setTerms(d.terms))
      .catch((err) => setError(err.message));
  }, []);
  useEffect(load, [load]);

  async function act(term, action, body) {
    setError("");
    try {
      await api.kbTermAction(term.term_id, action, body);
      load();
    } catch (err) {
      setError(err.message);
    }
  }

  const confirmed = (terms || []).filter((t) => t.status === "confirmed");

  return (
    <div className="flex flex-col gap-6">
      <ProposeTerm onAdded={load} />
      {error && <Alert tone="negative">{error}</Alert>}
      <Card>
        {!terms && <Skeleton className="m-5 h-24" />}
        {terms && terms.length === 0 && (
          <EmptyState icon={Tags} title="No terms yet">
            Runs propose the product parts a page names; you can also propose one above.
          </EmptyState>
        )}
        {terms && terms.length > 0 && (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Term</TableHead>
                <TableHead>Kind</TableHead>
                <TableHead>Also called</TableHead>
                <TableHead>Evidence</TableHead>
                <TableHead className="num">Entries</TableHead>
                <TableHead>Status</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {terms.map((t) => (
                <TableRow key={t.term_id}>
                  <TableCell className="font-medium">{t.label}</TableCell>
                  <TableCell>{t.kind}</TableCell>
                  <TableCell className="text-sm">{t.aliases.join(", ") || "—"}</TableCell>
                  <TableCell className="max-w-72 text-sm text-muted-fg">
                    {t.evidence_quote ? `“${t.evidence_quote}”` : "—"}
                    {t.evidence_count > 1 && ` (${t.evidence_count} sections)`}
                  </TableCell>
                  <TableCell className="num tabular-nums">{t.entry_count}</TableCell>
                  <TableCell>
                    {t.status === "proposed" && isManager ? (
                      <Decide term={t} confirmed={confirmed} onAct={act} />
                    ) : (
                      <Badge tone={TONE[t.status]}>
                        {t.status === "merged"
                          ? `merged into ${confirmed.find((c) => c.term_id === t.merged_into)?.label || t.merged_into}`
                          : t.status}
                      </Badge>
                    )}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </Card>
    </div>
  );
}

function Decide({ term, confirmed, onAct }) {
  const [into, setInto] = useState("");
  const others = confirmed.filter((c) => c.term_id !== term.term_id);
  return (
    <div className="flex flex-wrap items-center gap-1.5">
      <Button size="sm" onClick={() => onAct(term, "confirm")}>
        <Check aria-hidden="true" />
        Confirm
      </Button>
      <Button size="sm" variant="outline" onClick={() => onAct(term, "reject")}>
        <X aria-hidden="true" />
        Reject
      </Button>
      {others.length > 0 && (
        <>
          <Select className="w-36" aria-label={`Merge ${term.label} into`} value={into} onChange={(e) => setInto(e.target.value)}>
            <option value="">Merge into…</option>
            {others.map((c) => (
              <option key={c.term_id} value={c.term_id}>
                {c.label}
              </option>
            ))}
          </Select>
          <Button size="sm" variant="outline" disabled={!into} onClick={() => onAct(term, "merge", { into: Number(into) })}>
            <Merge aria-hidden="true" />
            Merge
          </Button>
        </>
      )}
    </div>
  );
}

function ProposeTerm({ onAdded }) {
  const [label, setLabel] = useState("");
  const [kind, setKind] = useState("module");
  const [aliases, setAliases] = useState("");
  const [error, setError] = useState("");
  const ids = { label: useId(), kind: useId(), aliases: useId() };

  async function submit(e) {
    e.preventDefault();
    setError("");
    try {
      await api.kbProposeTerm({
        label: label.trim(),
        kind,
        aliases: aliases.split(",").map((a) => a.trim()).filter(Boolean),
      });
      setLabel("");
      setAliases("");
      onAdded();
    } catch (err) {
      setError(err.message);
    }
  }

  return (
    <Card>
      <CardHeader>
        <div>
          <CardTitle>Propose a term</CardTitle>
          <CardDescription>A part of the product customers name. A manager confirms it.</CardDescription>
        </div>
      </CardHeader>
      <CardContent>
        <form className="grid items-end gap-4 sm:grid-cols-[minmax(0,2fr)_minmax(0,1fr)_minmax(0,3fr)_auto]" onSubmit={submit}>
          <Field label="Label" htmlFor={ids.label}>
            <Input id={ids.label} value={label} maxLength={41} onChange={(e) => setLabel(e.target.value)} required />
          </Field>
          <Field label="Kind" htmlFor={ids.kind}>
            <Select id={ids.kind} value={kind} onChange={(e) => setKind(e.target.value)}>
              {KINDS.map((k) => (
                <option key={k} value={k}>
                  {k}
                </option>
              ))}
            </Select>
          </Field>
          <Field label="Also called (comma-separated)" htmlFor={ids.aliases}>
            <Input id={ids.aliases} value={aliases} onChange={(e) => setAliases(e.target.value)} />
          </Field>
          <Button type="submit" variant="outline" disabled={!label.trim()}>
            <Plus aria-hidden="true" />
            Propose
          </Button>
        </form>
        {error && <Alert tone="negative" className="mt-3">{error}</Alert>}
      </CardContent>
    </Card>
  );
}
