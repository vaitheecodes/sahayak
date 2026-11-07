/* Shared wording for the knowledge-base screens: run states, the reason
 * codes runs and drafts record (kb_ingester/), and review flags. */

export const RUN_TONE = {
  estimated: "info",
  queued: "info",
  running: "info",
  done: "positive",
  stopped: "warning",
  failed: "negative",
  cancelled: "neutral",
};

const REASONS = {
  nothing_to_draft: "Nothing new to draft",
  run_cap: "Stopped at the per-run cap",
  daily_cap: "Stopped at today's cap",
  ai_unavailable: "AI unavailable",
  interrupted: "Interrupted by a restart",
  replaced: "Replaced by a newer estimate",
  internal_error: "Internal error",
  private_address: "Private address refused",
  metadata_address: "Metadata address refused",
  robots_disallowed: "robots.txt disallows it",
  too_large: "Page too large",
  timeout: "Timed out",
  bad_content_type: "Not a web page",
  dns_failed: "Host not found",
  tls_error: "TLS error",
  connect_failed: "Could not connect",
  too_many_redirects: "Too many redirects",
  quote_missing: "Step without a quote",
  quote_length: "Quote too short or long",
  quote_not_in_source: "Quote not in the page",
  not_supported: "Quote doesn't support the step",
  answer_verbatim: "Answer copied from the page",
  answer_too_close: "Answer too close to the page",
  howto_without_steps: "How-to left without steps",
  empty_entry: "Entry left empty",
  term_unsupported: "Term without evidence",
  invalid_entry: "Invalid entry",
  chunks_capped: "Sections over the page cap",
  entries_over_cap: "Entries over the 6 per section",
};

export function reasonLabel(code) {
  if (REASONS[code]) return REASONS[code];
  const http = /^http_(\d+)$/.exec(code || "");
  if (http) return `HTTP ${http[1]}`;
  return (code || "").replace(/_/g, " ");
}

export const FLAGS = {
  incomplete: ["warning", "Possibly incomplete"],
  duplicate: ["warning", "Possible duplicate"],
  stale: ["warning", "Source changed"],
  injection: ["negative", "Suspicious text"],
  answer_removed: ["info", "Answer removed"],
};

export const ENTRY_TONE = { draft: "info", approved: "positive", rejected: "neutral", retired: "neutral" };

export function formatDateTime(value) {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value);
  return date.toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
}
