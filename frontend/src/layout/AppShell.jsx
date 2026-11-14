import { useEffect, useState } from "react";
import { Menu } from "lucide-react";
import { NavLink } from "react-router-dom";
import { cn } from "@/lib/utils";
import { Button } from "@/ui/button";
import { Sheet, SheetContent, SheetTrigger } from "@/ui/sheet";
import { TooltipProvider } from "@/ui/tooltip";
import { NAV } from "./nav";
import ProductMark from "./ProductMark";
import UserMenu from "./UserMenu";
import { useMe } from "./useMe";
import { managerTypeLabel } from "@/lib/managerTypes";

/* A 56px top bar on white and the page on the cream background; cards are
 * the white shapes on it (warm-and-friendly re-skin, docs/DESIGN_SYSTEM.md).
 *
 * The full menu (every screen of the role, grouped) is hidden by default:
 * the menu button at the far left opens it as a slide-in panel with a scrim
 * (Radix Dialog: focus trapped, Escape or a scrim click closes it, the
 * button carries aria-expanded; picking a screen closes it too). The top
 * bar keeps only the role's main screens (nav.js `primary`); under 768px
 * those fold into the panel as well. Nothing is remembered: it always
 * starts closed. */

function Brand({ scope }) {
  const me = useMe();
  // A manager's type names the menu: "Manager, Platform Lead".
  if (me?.manager_type) scope = `${scope}, ${managerTypeLabel(me.manager_type)}`;
  return (
    <div className="flex h-12 items-center gap-2.5 pr-12 pl-4">
      <ProductMark />
      <div className="min-w-0 leading-tight">
        <div className="truncate font-display text-base font-bold text-fg">Help Desk</div>
        <div className="truncate text-xs text-muted-fg">{scope}</div>
      </div>
    </div>
  );
}

const itemClass = ({ isActive }) =>
  cn(
    "flex h-10 items-center gap-2.5 rounded-xl px-3 text-base text-muted-fg no-underline transition-colors outline-none",
    "hover:bg-active/70 hover:text-fg focus-visible:ring-2 focus-visible:ring-ring",
    isActive && "bg-green-tint font-bold text-green-tint-fg",
  );

function MenuNav({ role, counts = {}, onNavigate }) {
  const me = useMe();
  const groups = NAV[role].groups.map((g) => ({
    ...g,
    items: g.items.filter((item) => !item.needs || me?.permissions?.[item.needs]),
  }));
  return (
    <nav aria-label="Full menu" className="flex flex-col gap-5 px-2.5 pt-2 pb-6">
      {groups.map((group) => (
        <div key={group.label}>
          <div className="px-2.5 pb-1.5 text-xs font-medium text-muted-fg">{group.label}</div>
          <ul className="flex flex-col gap-0.5">
            {group.items.map(({ to, label, icon: Icon, end }) => (
              <li key={to}>
                <NavLink to={to} end={end} onClick={onNavigate} className={itemClass}>
                  <Icon aria-hidden="true" className="size-4 shrink-0" strokeWidth={1.75} />
                  <span className="flex-1 truncate">{label}</span>
                  {counts[to] ? (
                    <span className="rounded-full bg-sheet px-1.5 text-xs font-medium tabular-nums text-fg">
                      {counts[to]}
                    </span>
                  ) : null}
                </NavLink>
              </li>
            ))}
          </ul>
        </div>
      ))}
    </nav>
  );
}

// The role's main screens, inline in the top bar from 768px up.
function PrimaryNav({ role }) {
  return (
    <nav aria-label="Main" className="hidden items-center gap-1 md:flex">
      {NAV[role].primary.map(({ to, label, end }) => (
        <NavLink
          key={to}
          to={to}
          end={end}
          className={({ isActive }) =>
            cn(
              "inline-flex h-9 items-center rounded-full px-3.5 text-base font-bold text-muted-fg no-underline outline-none",
              "hover:text-fg focus-visible:ring-2 focus-visible:ring-ring",
              isActive && "bg-green-tint text-green-tint-fg",
            )
          }
        >
          {label}
        </NavLink>
      ))}
    </nav>
  );
}

export default function AppShell({ role, title, actions, counts, children, sheetClassName }) {
  const [open, setOpen] = useState(false);
  const { scope, primary } = NAV[role];
  // The title repeats nothing: on a main screen the highlighted top-bar item
  // already names the page, so the title shows only on phones there.
  const onPrimary = primary.some((p) => p.label === title);

  useEffect(() => {
    document.title = `${title} · Help Desk`;
  }, [title]);

  return (
    <TooltipProvider delayDuration={300}>
      <div className="flex min-h-dvh flex-col bg-frame text-fg md:h-dvh">
        <a
          href="#main"
          className="sr-only z-50 rounded-md bg-sheet px-3 py-2 focus:not-sr-only focus:fixed focus:top-2 focus:left-2"
        >
          Skip to content
        </a>

        <header className="sticky top-0 z-30 flex h-14 shrink-0 items-center gap-2 border-b border-border bg-sheet px-2 md:static md:px-4">
          <Sheet open={open} onOpenChange={setOpen}>
            <SheetTrigger asChild>
              <Button variant="ghost" size="icon" aria-label="Open the full menu">
                <Menu aria-hidden="true" />
              </Button>
            </SheetTrigger>
            <SheetContent title="Menu">
              <Brand scope={scope} />
              <div className="overflow-y-auto">
                <MenuNav role={role} counts={counts} onNavigate={() => setOpen(false)} />
              </div>
            </SheetContent>
          </Sheet>
          <span className="mr-2 hidden md:inline-flex" title="Help Desk">
            <ProductMark className="size-7" />
          </span>
          <PrimaryNav role={role} />
          <h1
            className={cn(
              "min-w-0 flex-1 truncate text-md font-bold md:ml-3 md:border-l md:border-border md:pl-4",
              onPrimary && "md:invisible",
            )}
          >
            {title}
          </h1>
          {actions && <div className="hidden items-center gap-2 sm:flex">{actions}</div>}
          <UserMenu role={role} />
        </header>

        <main
          id="main"
          tabIndex={-1}
          className={cn(
            "min-h-[calc(100dvh-3.5rem)] flex-1 bg-frame outline-none md:min-h-0 md:overflow-y-auto",
            sheetClassName,
          )}
        >
          {actions && <div className="flex flex-wrap items-center gap-2 px-4 pt-4 sm:hidden">{actions}</div>}
          {children}
        </main>
      </div>
    </TooltipProvider>
  );
}

/* Standard page padding inside the sheet, with an optional lead line (the
 * screen's one finding or what the page is for) and a toolbar. */
export function Page({ lead, toolbar, className, children }) {
  return (
    <div className={cn("flex flex-col gap-6 p-4 md:p-6", className)}>
      {(lead || toolbar) && (
        <div className="flex flex-wrap items-center justify-between gap-3">
          {lead && <p className="max-w-[72ch] text-base text-muted-fg">{lead}</p>}
          {toolbar && <div className="flex flex-wrap items-center gap-2">{toolbar}</div>}
        </div>
      )}
      {children}
    </div>
  );
}
