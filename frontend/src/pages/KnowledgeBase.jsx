import { Navigate, useParams } from "react-router-dom";
import { getRole } from "@/api";
import AppShell, { Page } from "@/layout/AppShell";
import SourcesPanel from "@/components/kb/SourcesPanel";
import ReviewQueue from "@/components/kb/ReviewQueue";
import EntryEditor from "@/components/kb/EntryEditor";
import TermsPanel from "@/components/kb/TermsPanel";
import CategoriesPanel from "@/components/kb/CategoriesPanel";

/* The knowledge base: where entries come from (Sources), the drafts to
 * review, and the product terms and categories learned from the content.
 * Technicians and managers; only managers add sources, start runs and
 * decide (the backend enforces it, kb_ingester/api.py). */

const SECTIONS = {
  review: ["Review queue", "Drafts from the sources wait here. Nothing reaches customers until a manager approves it."],
  sources: ["Sources", "Public pages the knowledge base is drafted from. Each run shows its cost before it starts."],
  terms: ["Terms", "Parts of the product the content names. Only confirmed terms change how the bot picks a guide."],
  categories: ["Categories", "What tickets and entries are filed under. Proposed ones are used once confirmed."],
};

export default function KnowledgeBase() {
  const { section = "review", id } = useParams();
  const role = getRole();
  const isManager = role === "manager";
  if (!SECTIONS[section]) return <Navigate to="/kb/review" replace />;
  const [title, lead] = SECTIONS[section];
  const editing = section === "review" && id;

  return (
    <AppShell role={role} title={editing ? `Review ${id}` : title}>
      <Page lead={editing ? null : lead}>
        {section === "sources" && <SourcesPanel isManager={isManager} />}
        {section === "review" && !id && <ReviewQueue />}
        {editing && <EntryEditor entryId={id} isManager={isManager} />}
        {section === "terms" && <TermsPanel isManager={isManager} />}
        {section === "categories" && <CategoriesPanel isManager={isManager} />}
      </Page>
    </AppShell>
  );
}
