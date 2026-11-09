import { useState } from "react";
import { getToken } from "@/api";
import { subjectFromToken } from "@/lib/tokenRole";

/* Classic or Kanban, remembered per user in this browser (a convenience:
 * storage can be missing or blocked, and then it is simply Classic). */
export const DASHBOARD_STYLES = ["classic", "kanban"];

export function useDashboardStyle() {
  const key = `dashboardStyle:${subjectFromToken(getToken()) || "anon"}`;
  const [style, setStyle] = useState(() => {
    try {
      const saved = localStorage.getItem(key);
      return DASHBOARD_STYLES.includes(saved) ? saved : "classic";
    } catch {
      return "classic";
    }
  });
  function choose(next) {
    setStyle(next);
    try {
      localStorage.setItem(key, next);
    } catch {
      /* not remembered */
    }
  }
  return [style, choose];
}
