import {
  Activity,
  LayoutDashboard,
  ClipboardCheck,
  Globe,
  Shapes,
  Tags,
  Building2,
  FlaskConical,
  Inbox,
  LifeBuoy,
  MessageSquareText,
  MessagesSquare,
  Radar,
  Settings2,
  Siren,
  Ticket,
  Timer,
  Users,
} from "lucide-react";

/* The sidebar for each role: groups of links to whole screens (never
 * anchors into one page). The backend enforces the same boundaries: a
 * link missing here is a 403 there (tests/test_role_scope.py). */

// Technicians edit drafts and propose terms; managers also add sources,
// run them and decide (kb_ingester/api.py).
const KNOWLEDGE_BASE = {
  label: "Knowledge base",
  items: [
    { to: "/kb/review", label: "Review queue", icon: ClipboardCheck },
    { to: "/kb/sources", label: "Sources", icon: Globe },
    { to: "/kb/terms", label: "Terms", icon: Tags },
    { to: "/kb/categories", label: "Categories", icon: Shapes },
    { to: "/try-a-ticket", label: "Try a ticket", icon: FlaskConical },
  ],
};

export const NAV = {
  customer: {
    scope: "Customer support",
    groups: [
      {
        label: "Support",
        items: [
          { to: "/customer", label: "Get help", icon: LifeBuoy, end: true },
          { to: "/customer/tickets", label: "My tickets", icon: Ticket },
          { to: "/customer/chats", label: "Chats", icon: MessagesSquare },
        ],
      },
      { label: "Resources", items: [{ to: "/incidents", label: "Service history", icon: Radar }] },
    ],
  },
  technician: {
    scope: "Technician workspace",
    groups: [
      {
        label: "My work",
        items: [
          { to: "/technician", label: "Dashboard", icon: LayoutDashboard, end: true },
          { to: "/technician/tickets", label: "Tickets", icon: Inbox },
          { to: "/technician/chats", label: "Chats", icon: MessagesSquare },
        ],
      },
      {
        label: "More",
        items: [
          { to: "/technician/chat-reviews", label: "Chat reviews", icon: MessageSquareText },
          { to: "/kb/review", label: "KB review queue", icon: ClipboardCheck },
          { to: "/try-a-ticket", label: "Try a ticket", icon: FlaskConical },
        ],
      },
    ],
  },
  // Everything a manager sees is limited to their own department.
  manager: {
    scope: "Manager",
    groups: [
      {
        label: "Overview",
        items: [
          { to: "/manager", label: "Dashboard", icon: LayoutDashboard, end: true },
          { to: "/manager/sla", label: "SLA", icon: Timer },
        ],
      },
      {
        label: "Work",
        items: [
          { to: "/manager/tickets", label: "Department tickets", icon: Inbox },
          { to: "/manager/chats", label: "Chats", icon: MessagesSquare },
          { to: "/manager/chat-reviews", label: "Chat reviews", icon: MessageSquareText },
          { to: "/manager/incidents", label: "Incidents", icon: Siren },
        ],
      },
      KNOWLEDGE_BASE,
    ],
  },
  // People and system only: no tickets, dashboards or SLA (the managers').
  admin: {
    scope: "Admin console",
    groups: [
      {
        label: "People",
        items: [
          { to: "/admin", label: "Users", icon: Users, end: true },
          { to: "/admin/departments", label: "Departments", icon: Building2 },
        ],
      },
      {
        label: "System",
        items: [
          { to: "/admin/settings", label: "Settings", icon: Settings2 },
          { to: "/admin/activity", label: "Activity log", icon: Activity },
        ],
      },
    ],
  },
};

export const ROLE_LABEL = {
  customer: "Customer",
  technician: "Technician",
  manager: "Manager",
  admin: "Admin",
};

