import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "@/api";
import { managerTypeLabel } from "@/lib/managerTypes";
import { Alert } from "@/ui/alert";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/ui/card";
import { Skeleton } from "@/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/ui/table";

/* Teams (Platform Lead only, GET /api/manager/teams): a team is a
 * department, its managers and the support engineers who work it, then the
 * people in no department. Open counts are tickets assigned now; the admin
 * moves people between teams under Users. */

function Managers({ managers }) {
  if (managers.length === 0) return <p className="m-0 text-sm text-muted-fg">No manager.</p>;
  return (
    <ul className="m-0 flex list-none flex-wrap gap-x-5 gap-y-1 p-0 text-sm">
      {managers.map((m) => (
        <li key={m.staff_id}>
          <span className="font-medium">{m.name}</span>{" "}
          <span className="text-muted-fg">{managerTypeLabel(m.manager_type)}</span>
        </li>
      ))}
    </ul>
  );
}

function Engineers({ engineers }) {
  if (engineers.length === 0)
    return <p className="m-0 px-5 pb-4 text-sm text-muted-fg">No support engineers work here yet.</p>;
  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>Support engineer</TableHead>
          <TableHead className="num">Open now</TableHead>
          <TableHead className="num">Resolved</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {engineers.map((e) => (
          <TableRow key={e.staff_id}>
            <TableCell>{e.name}</TableCell>
            <TableCell className="num tabular-nums">{e.open}</TableCell>
            <TableCell className="num tabular-nums">{e.resolved}</TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}

function Team({ name, team, department_id: departmentId }) {
  const open = team.engineers.reduce((sum, e) => sum + e.open, 0);
  return (
    <Card>
      <CardHeader className="flex-wrap">
        <div className="min-w-0">
          <CardTitle>{name}</CardTitle>
          <CardDescription>
            {team.engineers.length} support engineer{team.engineers.length === 1 ? "" : "s"}, {open} open ticket
            {open === 1 ? "" : "s"}
          </CardDescription>
        </div>
        {departmentId && (
          <Link className="text-sm" to={`/manager/tickets?department=${encodeURIComponent(departmentId)}`}>
            Its tickets
          </Link>
        )}
      </CardHeader>
      <CardContent className="pb-3">
        <Managers managers={team.managers} />
      </CardContent>
      <Engineers engineers={team.engineers} />
    </Card>
  );
}

export default function Teams() {
  const [data, setData] = useState(null);
  const [error, setError] = useState("");

  useEffect(() => {
    api
      .managerTeams()
      .then(setData)
      .catch((err) => setError(err.message));
  }, []);

  if (error) return <Alert tone="negative">{error}</Alert>;
  if (!data) return <Skeleton className="h-64" />;
  const nobody = data.no_department;
  return (
    <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
      {data.departments.map((d) => (
        <Team key={d.department_id} name={d.name} department_id={d.department_id} team={d} />
      ))}
      {(nobody.managers.length > 0 || nobody.engineers.length > 0) && <Team name="No department" team={nobody} />}
    </div>
  );
}
