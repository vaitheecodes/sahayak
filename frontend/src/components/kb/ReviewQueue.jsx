import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { ClipboardCheck } from "lucide-react";
import { api } from "@/api";
import { Alert } from "@/ui/alert";
import { Badge } from "@/ui/badge";
import { Card } from "@/ui/card";
import { EmptyState } from "@/ui/empty-state";
import { Select } from "@/ui/input";
import { Skeleton } from "@/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/ui/table";
import { Tabs, TabsList, TabsTrigger } from "@/ui/tabs";
import { categoryLabel } from "@/utils/categories";
import { ENTRY_TONE, FLAGS } from "./format";

const STATUSES = [
  ["draft", "Drafts"],
  ["approved", "Approved"],
  ["rejected", "Rejected"],
  ["all", "All"],
];

export default function ReviewQueue() {
  const [status, setStatus] = useState("draft");
  const [flag, setFlag] = useState("");
  const [entries, setEntries] = useState(null);
  const [error, setError] = useState("");
  const navigate = useNavigate();

  useEffect(() => {
    setEntries(null);
    api
      .kbEntries({ status, flag })
      .then((d) => setEntries(d.entries))
      .catch((err) => setError(err.message));
  }, [status, flag]);

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <Tabs value={status} onValueChange={setStatus}>
          <TabsList aria-label="Status">
            {STATUSES.map(([value, label]) => (
              <TabsTrigger key={value} value={value}>
                {label}
              </TabsTrigger>
            ))}
          </TabsList>
        </Tabs>
        <Select className="w-52" aria-label="Flag" value={flag} onChange={(e) => setFlag(e.target.value)}>
          <option value="">Any flag</option>
          {Object.entries(FLAGS).map(([value, [, label]]) => (
            <option key={value} value={value}>
              {label}
            </option>
          ))}
        </Select>
      </div>
      {error && <Alert tone="negative">{error}</Alert>}
      <Card>
        {!entries && !error && <Skeleton className="m-5 h-24" />}
        {entries && entries.length === 0 && (
          <EmptyState icon={ClipboardCheck} title="Nothing here">
            {status === "draft" ? "Run a source to draft entries for review." : "No entries match."}
          </EmptyState>
        )}
        {entries && entries.length > 0 && (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Entry</TableHead>
                <TableHead>Category</TableHead>
                <TableHead className="num">Steps</TableHead>
                <TableHead>Flags</TableHead>
                <TableHead>Source</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {entries.map((e) => (
                <TableRow
                  key={e.kb_entry_id}
                  className="cursor-pointer"
                  onClick={() => navigate(`/kb/review/${e.kb_entry_id}`)}
                >
                  <TableCell>
                    <a
                      href={`/kb/review/${e.kb_entry_id}`}
                      onClick={(ev) => {
                        ev.preventDefault();
                        navigate(`/kb/review/${e.kb_entry_id}`);
                      }}
                      className="font-medium text-fg hover:underline"
                    >
                      {e.title}
                    </a>
                    <div className="flex items-center gap-2 text-sm text-muted-fg">
                      <span className="font-mono">{e.kb_entry_id}</span>
                      {status === "all" && <Badge tone={ENTRY_TONE[e.status]}>{e.status}</Badge>}
                      <span>{e.kind || "—"}</span>
                    </div>
                  </TableCell>
                  <TableCell>{categoryLabel(e.category)}</TableCell>
                  <TableCell className="num tabular-nums">{e.step_count}</TableCell>
                  <TableCell>
                    <div className="flex flex-wrap gap-1">
                      {e.flags.map((f) => (
                        <Badge key={f} tone={FLAGS[f]?.[0]}>
                          {f === "duplicate"
                            ? `${FLAGS[f][1]} of ${e.duplicate_of}`
                            : f === "incomplete" && e.completeness
                              ? `${FLAGS[f][1]} (${e.completeness.kept} of ${e.completeness.expected})`
                              : FLAGS[f]?.[1] || f}
                        </Badge>
                      ))}
                    </div>
                  </TableCell>
                  <TableCell className="text-sm text-muted-fg">{e.source_name || "Imported"}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </Card>
    </div>
  );
}
