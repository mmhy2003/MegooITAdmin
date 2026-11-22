import { Search } from "lucide-react";
import { Button } from "@/components/ui/button";

/** Where search will go (Phase 6); disabled until then, with no shortcut listener. */
export function SearchPlaceholder() {
  return (
    <>
      <Button
        variant="outline"
        disabled
        aria-label="Search, not available yet"
        className="hidden w-56 justify-between font-normal normal-case tracking-normal text-muted-foreground md:inline-flex"
      >
        <span className="flex items-center gap-2">
          <Search aria-hidden />
          Search…
        </span>
        <kbd className="rounded border px-1.5 font-mono text-[11px]">Ctrl K</kbd>
      </Button>
      <Button variant="ghost" size="icon" disabled aria-label="Search, not available yet" className="md:hidden">
        <Search aria-hidden />
      </Button>
    </>
  );
}
