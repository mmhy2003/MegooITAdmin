import { Button } from "@/components/ui/button";

export type DashboardView = "cards" | "table";

const VIEWS: { view: DashboardView; label: string }[] = [
  { view: "cards", label: "Cards" },
  { view: "table", label: "Table" },
];

/** Two toggle buttons choosing how the Dashboard lays out its servers. */
export function ViewSwitch({ view, onChange }: { view: DashboardView; onChange: (view: DashboardView) => void }) {
  return (
    <div role="group" aria-label="View" className="inline-flex gap-1 rounded-md border p-0.5">
      {VIEWS.map((v) => (
        <Button
          key={v.view}
          type="button"
          size="sm"
          variant={v.view === view ? "secondary" : "ghost"}
          aria-pressed={v.view === view}
          onClick={() => onChange(v.view)}
        >
          {v.label}
        </Button>
      ))}
    </div>
  );
}
