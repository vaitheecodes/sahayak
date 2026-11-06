import { useCallback, useEffect, useState } from "react";
import { Check, Merge, X } from "lucide-react";
import { api } from "@/api";
import { Alert } from "@/ui/alert";
import { Badge } from "@/ui/badge";
import { Button } from "@/ui/button";
import { Card } from "@/ui/card";
import { Select } from "@/ui/input";
import { Skeleton } from "@/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/ui/table";
import { setCategoryLabels } from "@/utils/categories";

/* Categories: the confirmed ones tickets and entries are filed under, and
 * the ones runs proposed. A manager confirms, rejects, or merges a
 * proposal into a confirmed category; drafts that asked for it move. */

const TONE = { proposed: "info", confirmed: "positive", rejected: "neutral", merged: "neutral" };

export default function CategoriesPanel({ isManager }) {
  const [rows, setRows] = useState(null);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");

  const load = useCallback(() => {
    api
      .kbCategories()
      .then((d) => {
        setRows(d.categories);
        setCategoryLabels(Object.fromEntries(d.categories.filter((c) => c.status === "confirmed").map((c) => [c.name, c.label])));
      })
      .catch((err) => setError(err.message));
  }, []);
  useEffect(load, [load]);

  async function act(row, action, body) {
    setError("");
    setMessage("");
    try {
      const res = await api.kbCategoryAction(row.name, action, body);
      if (res.drafts_moved) setMessage(`${res.drafts_moved} draft(s) moved to it.`);
      load();
    } catch (err) {
      setError(err.message);
    }
  }

  if (!rows) return error ? <Alert tone="negative">{error}</Alert> : <Skeleton className="h-40" />;
  const confirmed = rows.filter((r) => r.status === "confirmed");

  return (
    <div className="flex flex-col gap-4">
      {error && <Alert tone="negative">{error}</Alert>}
      {message && <Alert tone="positive">{message}</Alert>}
      <Card>
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Category</TableHead>
              <TableHead>Description</TableHead>
              <TableHead>From</TableHead>
              <TableHead>Status</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {rows.map((r) => (
              <TableRow key={r.name}>
                <TableCell>
                  <div className="font-medium">{r.label}</div>
                  <div className="font-mono text-sm text-muted-fg">{r.name}</div>
                </TableCell>
                <TableCell className="text-sm">{r.description || "—"}</TableCell>
                <TableCell className="text-sm text-muted-fg">{r.source === "ingester" ? "Proposed by a run" : r.source}</TableCell>
                <TableCell>
                  {r.status === "proposed" && isManager ? (
                    <Decide row={r} confirmed={confirmed} onAct={act} />
                  ) : (
                    <Badge tone={TONE[r.status]}>{r.status === "merged" ? `merged into ${r.merged_into}` : r.status}</Badge>
                  )}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </Card>
    </div>
  );
}

function Decide({ row, confirmed, onAct }) {
  const [into, setInto] = useState("");
  return (
    <div className="flex flex-wrap items-center gap-1.5">
      <Button size="sm" onClick={() => onAct(row, "confirm")}>
        <Check aria-hidden="true" />
        Confirm
      </Button>
      <Button size="sm" variant="outline" onClick={() => onAct(row, "reject")}>
        <X aria-hidden="true" />
        Reject
      </Button>
      <Select className="w-40" aria-label={`Merge ${row.label} into`} value={into} onChange={(e) => setInto(e.target.value)}>
        <option value="">Merge into…</option>
        {confirmed.map((c) => (
          <option key={c.name} value={c.name}>
            {c.label}
          </option>
        ))}
      </Select>
      <Button size="sm" variant="outline" disabled={!into} onClick={() => onAct(row, "merge", { into })}>
        <Merge aria-hidden="true" />
        Merge
      </Button>
    </div>
  );
}
