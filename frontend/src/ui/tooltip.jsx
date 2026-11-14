import { Tooltip as T } from "radix-ui";
import { cn } from "@/lib/utils";

export const TooltipProvider = T.Provider;

/* Short label for an icon-only control; the control keeps its own
 * accessible name. */
export function Tooltip({ content, children, side = "top" }) {
  return (
    <T.Root>
      <T.Trigger asChild>{children}</T.Trigger>
      <T.Portal>
        <T.Content
          side={side}
          sideOffset={6}
          className={cn("z-50 rounded-lg bg-fg px-2.5 py-1 text-xs font-bold text-sheet shadow-pop")}
        >
          {content}
        </T.Content>
      </T.Portal>
    </T.Root>
  );
}
