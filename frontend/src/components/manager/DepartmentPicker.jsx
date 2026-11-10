import { useId } from "react";
import { Select } from "@/ui/input";

/* A Platform Lead's department dropdown (lib/managerScope.js): all
 * departments, or one. The server checks the scope again on every call. */
export default function DepartmentPicker({ value, onChange, departments }) {
  const id = useId();
  return (
    <div className="flex items-center gap-2">
      <label htmlFor={id} className="text-sm text-muted-fg">
        Department
      </label>
      <Select id={id} className="w-52" value={value} onChange={(e) => onChange(e.target.value)}>
        <option value="all">All departments</option>
        {departments.map((d) => (
          <option key={d.department_id} value={d.department_id}>
            {d.name}
          </option>
        ))}
      </Select>
    </div>
  );
}
