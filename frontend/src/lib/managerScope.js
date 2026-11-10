import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { api } from "@/api";
import { useMe } from "@/layout/useMe";

/* The department a manager is looking at. Only a manager whose type sees
 * every department (a Platform Lead, backend/permissions.py) picks one:
 * ?department=<id> in the URL, kept across Dashboard, SLA and Department
 * tickets; none means all. Everyone else gets `department` undefined and
 * the server uses their own department. */
export function useManagerScope() {
  const me = useMe();
  const [params, setParams] = useSearchParams();
  const [departments, setDepartments] = useState([]);
  const canPick = me?.permissions?.tickets === "all";
  const allowsTeams = Boolean(me?.permissions?.teams);

  useEffect(() => {
    if (!canPick) return;
    api.managerDepartments().then(setDepartments).catch(() => {});
  }, [canPick]);

  const department = canPick ? params.get("department") || "all" : undefined;
  function setDepartment(value) {
    const next = new URLSearchParams(params);
    if (value && value !== "all") next.set("department", value);
    else next.delete("department");
    setParams(next, { replace: true });
  }
  return { ready: me !== null, canPick, allowsTeams, department, setDepartment, departments };
}
