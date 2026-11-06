/* Customer-facing category labels. Categories are data (backend
 * categories.py): the labels come from /api/meta, loaded once before the
 * app renders (main.jsx). A name without a label reads as a phrase. */
let labels = {};

export function setCategoryLabels(next) {
  labels = { ...(next || {}) };
}

export function categoryLabel(value) {
  if (!value) return "—";
  return labels[value] || value.replace(/_/g, " ").toLowerCase().replace(/^\w/, (c) => c.toUpperCase());
}
