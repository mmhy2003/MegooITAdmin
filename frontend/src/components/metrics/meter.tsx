import { toneOf, type Tone } from "@/lib/metrics";
import { cn } from "@/lib/utils";

const FILL: Record<Tone, string> = { normal: "bg-cyan", amber: "bg-amber", pink: "bg-pink" };

/** A thin bar for a percentage; the number beside it carries the value, so the bar is hidden from assistive technology. */
export function Meter({ percent }: { percent: number | null }) {
  return (
    <div aria-hidden className="h-1.5 w-full overflow-hidden rounded-full bg-surface-2">
      {percent !== null && (
        <div
          data-slot="meter-fill"
          className={cn("h-full rounded-full", FILL[toneOf(percent)])}
          style={{ width: `${Math.min(Math.max(percent, 0), 100)}%` }}
        />
      )}
    </div>
  );
}
