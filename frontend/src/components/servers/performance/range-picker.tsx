import { Button } from "@/components/ui/button";
import { RANGE_LABELS, RANGES, type RangeName } from "@/lib/metrics";

/** Toggle buttons choosing the time range of the Performance tab's charts. */
export function RangePicker({ range, onChange }: { range: RangeName; onChange: (range: RangeName) => void }) {
  return (
    <div role="group" aria-label="Time range" className="inline-flex flex-wrap gap-1 rounded-md border p-0.5">
      {RANGES.map((r) => (
        <Button
          key={r}
          type="button"
          size="sm"
          variant={r === range ? "secondary" : "ghost"}
          aria-pressed={r === range}
          onClick={() => onChange(r)}
        >
          {RANGE_LABELS[r]}
        </Button>
      ))}
    </div>
  );
}
