import { useState } from "react";
import { ChevronDown, KeyRound, LogOut, Monitor, Moon, Sun } from "lucide-react";
import { useNavigate } from "react-router-dom";
import { getTheme, setTheme } from "@/utils/theme";
import { clearSession } from "@/api";
import { Avatar } from "@/ui/avatar";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/ui/dropdown-menu";
import { ROLE_LABEL } from "./nav";
import { useMe } from "./useMe";

const THEMES = [
  ["system", "System", Monitor],
  ["light", "Light", Sun],
  ["dark", "Dark", Moon],
];

export default function UserMenu({ role }) {
  const navigate = useNavigate();
  const [theme, setThemeState] = useState(getTheme);
  const me = useMe();
  const name = me?.name || ROLE_LABEL[role];

  function logout() {
    clearSession();
    navigate("/login");
  }

  return (
    <DropdownMenu>
      <DropdownMenuTrigger
        className="inline-flex h-10 cursor-pointer items-center gap-2 rounded-full border-0 bg-transparent pr-2 pl-1 text-base text-fg outline-none hover:bg-active focus-visible:ring-2 focus-visible:ring-ring"
        aria-label={`Account: ${name}`}
      >
        <Avatar name={name} className="size-8" />
        <span className="hidden max-w-36 truncate font-medium sm:inline">{name}</span>
        <ChevronDown aria-hidden="true" className="size-3.5 text-muted-fg" />
      </DropdownMenuTrigger>
      <DropdownMenuContent className="w-60">
        <DropdownMenuLabel className="flex flex-col gap-0.5 py-2">
          <span className="truncate text-base font-medium text-fg">{name}</span>
          {me?.email && <span className="truncate">{me.email}</span>}
          <span>{ROLE_LABEL[role]}</span>
        </DropdownMenuLabel>
        <DropdownMenuSeparator />
        <DropdownMenuLabel>Appearance</DropdownMenuLabel>
        <DropdownMenuRadioGroup
          value={theme}
          onValueChange={(value) => {
            setTheme(value);
            setThemeState(value);
          }}
        >
          {THEMES.map(([value, label, Icon]) => (
            <DropdownMenuRadioItem key={value} value={value}>
              <Icon aria-hidden="true" />
              {label}
            </DropdownMenuRadioItem>
          ))}
        </DropdownMenuRadioGroup>
        <DropdownMenuSeparator />
        <DropdownMenuItem onSelect={() => navigate("/change-password")}>
          <KeyRound aria-hidden="true" />
          Change password
        </DropdownMenuItem>
        <DropdownMenuItem onSelect={logout}>
          <LogOut aria-hidden="true" />
          Log out
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
