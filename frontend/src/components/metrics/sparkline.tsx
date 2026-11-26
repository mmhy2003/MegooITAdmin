import { cn } from "@/lib/utils";

const WIDTH = 60;
const HEIGHT = 16;

/** The path of a line through `values`; a null ends a segment and the next value starts a new one. */
function pathOf(values: (number | null)[], max: number): string {
  const step = values.length > 1 ? WIDTH / (values.length - 1) : 0;
  let d = "";
  let drawing = false;
  values.forEach((value, i) => {
    if (value === null) {
      drawing = false;
      return;
    }
    const ratio = Math.min(Math.max(value / max, 0), 1);
    const x = Math.round(i * step * 100) / 100;
    const y = Math.round((HEIGHT - 1 - ratio * (HEIGHT - 2)) * 100) / 100;
    d += `${drawing ? "L" : "M"}${x} ${y}`;
    drawing = true;
  });
  return d;
}

/** A small line of recent values, drawn in the current text colour. */
export function Sparkline({
  values,
  max = 100,
  label,
  className,
}: {
  values: (number | null)[];
  max?: number;
  label: string;
  className?: string;
}) {
  const d = pathOf(values, max);
  return (
    <svg
      role="img"
      aria-label={label}
      viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
      preserveAspectRatio="none"
      className={cn("h-4 w-15", className)}
    >
      {d && <path d={d} fill="none" stroke="currentColor" strokeWidth={2} strokeLinejoin="round" />}
    </svg>
  );
}
