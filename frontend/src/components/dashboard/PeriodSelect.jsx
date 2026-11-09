import { useId } from "react";
import { Select } from "@/ui/input";

/* The reporting period of the manager and technician dashboards: fixed
 * presets only, computed by the server in IST with weeks starting Monday
 * (backend/periods.py). */

export const PERIODS = [
  ["today", "Today"],
  ["yesterday", "Yesterday"],
  ["this_week", "This week"],
  ["last_week", "Last week"],
  ["this_month", "This month"],
  ["last_month", "Last month"],
  ["this_quarter", "This quarter"],
  ["this_year", "This year"],
];
export const DEFAULT_PERIOD = "this_week";

export default function PeriodSelect({ value, onChange }) {
  const id = useId();
  return (
    <div className="flex items-center gap-2">
      <label htmlFor={id} className="text-sm text-muted-fg">
        Period
      </label>
      <Select id={id} className="w-40" value={value} onChange={(e) => onChange(e.target.value)}>
        {PERIODS.map(([key, label]) => (
          <option key={key} value={key}>
            {label}
          </option>
        ))}
      </Select>
    </div>
  );
}
