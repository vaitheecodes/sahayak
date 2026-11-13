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
  Network,
  Radar,
  Settings2,
  Siren,
  Ticket,
  Timer,
  Users,
  MessageCircleQuestion,
} from "lucide-react";

/* The menu for each role: `groups` is the full menu (the slide-in panel),
 * links to whole screens (never anchors into one page); `primary` are the
 * main screens shown in the top bar. The backend enforces the same
 * boundaries: a link missing here is a 403 there (tests/test_role_scope.py).
 * An item with `needs` shows only when /auth/me's `permissions` has it
 * (a manager type's, backend/permissions.py). */

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
    primary: [
      { to: "/customer", label: "Get help", end: true },
      { to: "/customer/tickets", label: "My tickets" },
      { to: "/customer/chats", label: "Chats" },
    ],
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
    scope: "Support engineer workspace",
    primary: [
      { to: "/technician", label: "Dashboard", end: true },
      { to: "/technician/tickets", label: "Tickets" },
    ],
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
  // Everything a manager sees is limited to their own department (a
  // Platform Lead: every department, and Teams).
  manager: {
    scope: "Manager",
    primary: [
      { to: "/manager", label: "Dashboard", end: true },
      { to: "/manager/tickets", label: "Tickets" },
    ],
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
          { to: "/manager/teams", label: "Teams", icon: Network, needs: "teams" },
          { to: "/manager/unanswered", label: "Unanswered questions", icon: MessageCircleQuestion, needs: "unanswered" },
        ],
      },
      KNOWLEDGE_BASE,
    ],
  },
  // People and system only: no tickets, dashboards or SLA (the managers').
  admin: {
    scope: "Admin console",
    primary: [
      { to: "/admin", label: "Users", end: true },
      { to: "/admin/settings", label: "Settings" },
    ],
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
  technician: "Support Engineer",
  manager: "Manager",
  admin: "Admin",
};

