/* The technician dropdown on Department tickets: Unassigned, then the
 * department's technicians. A ticket claimed by someone outside the
 * department keeps its owner visible as one extra, disabled option, so the
 * select never falls back to "Unassigned" for a ticket that has an owner.
 * Tested under Node by tests/test_frontend_assignee.py. */
export function assigneeOptions(ticket, technicians) {
  const options = [
    { value: "", label: "Unassigned", disabled: false },
    ...technicians.map((t) => ({ value: t.staff_id, label: t.name, disabled: false })),
  ];
  const owner = ticket.assigned_technician_id;
  if (owner && !technicians.some((t) => t.staff_id === owner)) {
    options.push({
      value: owner,
      label: `${ticket.technician_name || owner} (outside your department)`,
      disabled: true,
    });
  }
  return options;
}
