import { formatPercent, toneOf } from "@/lib/metrics";
import { cn } from "@/lib/utils";

/** A percentage with a ▲ and a spoken word from the warning levels, so the warning never depends on colour alone. */
export function PercentValue({ value, className }: { value: number | null; className?: string }) {
  const tone = toneOf(value);
  return (
    <span
      className={cn(
        "tabular-nums",
        tone === "amber" && "text-amber-ink",
        tone === "pink" && "text-pink-ink",
        className,
      )}
    >
      {formatPercent(value)}
      {tone !== "normal" && (
        <>
          <span aria-hidden> ▲</span>
          <span className="sr-only">{tone === "pink" ? "very high" : "high"}</span>
        </>
      )}
    </span>
  );
}
