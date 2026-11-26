"use client";

import { Area, CartesianGrid, ComposedChart, Line, XAxis, YAxis } from "recharts";
import { type ChartConfig, ChartContainer, ChartTooltip, ChartTooltipContent } from "@/components/ui/chart";
import { chartRows, type ChartLine, formatBytes, formatLoad, formatPercent, formatRate } from "@/lib/metrics";
import { cn } from "@/lib/utils";

export type ChartUnit = "percent" | "bytes" | "rate" | "load";

const FORMAT: Record<ChartUnit, (v: number | null) => string> = {
  percent: formatPercent,
  bytes: formatBytes,
  rate: formatRate,
  load: formatLoad,
};
const TWO_DAYS_MS = 2 * 24 * 60 * 60_000;
const HOURS = new Intl.DateTimeFormat(undefined, { hour: "2-digit", minute: "2-digit" });
const DAYS = new Intl.DateTimeFormat(undefined, { day: "numeric", month: "short" });
const FULL = new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "medium" });

function Swatch({ color }: { color: string }) {
  return <span aria-hidden className="h-0.5 w-3 shrink-0 rounded-full" style={{ backgroundColor: color }} />;
}

/** A time chart of one or more lines on one y axis, each with an optional min–max band, in the browser's time
 * zone. Two lines or more get a legend; the label names the figure. */
export function MetricChart({
  lines,
  stepMs,
  unit,
  label,
  dimmed = false,
  height = 180,
}: {
  lines: ChartLine[];
  stepMs: number;
  unit: ChartUnit;
  label: string;
  dimmed?: boolean;
  height?: number;
}) {
  const rows = chartRows(lines, stepMs);
  const config: ChartConfig = Object.fromEntries(lines.map((line) => [line.key, { label: line.label, color: line.color }]));
  const span = rows.length > 1 ? rows[rows.length - 1].t - rows[0].t : 0;
  const tick = span < TWO_DAYS_MS ? HOURS : DAYS;
  const format = FORMAT[unit];

  return (
    <figure aria-label={label} className={cn("grid gap-2", dimmed && "opacity-50")}>
      {lines.length >= 2 && (
        <ul className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-foreground">
          {lines.map((line) => (
            <li key={line.key} className="flex items-center gap-1.5">
              <Swatch color={line.color} />
              {line.label}
            </li>
          ))}
        </ul>
      )}
      <ChartContainer config={config} className="aspect-auto w-full" style={{ height }}>
        <ComposedChart data={rows} margin={{ top: 4, right: 4, bottom: 0, left: 0 }}>
          <CartesianGrid vertical={false} stroke="var(--grid)" />
          <XAxis
            dataKey="t"
            type="number"
            scale="time"
            domain={["dataMin", "dataMax"]}
            tickFormatter={(t: number) => tick.format(t)}
            tickLine={false}
            axisLine={false}
            minTickGap={24}
          />
          <YAxis
            domain={unit === "percent" ? [0, 100] : undefined}
            tickFormatter={(v: number) => format(v)}
            tickLine={false}
            axisLine={false}
            width={64}
          />
          <ChartTooltip
            cursor
            content={
              <ChartTooltipContent
                labelFormatter={(_, payload) => {
                  const t = payload?.[0]?.payload?.t;
                  return typeof t === "number" ? FULL.format(t) : null;
                }}
                formatter={(value, name, item) => (
                  <>
                    <Swatch color={item.color ?? "currentColor"} />
                    <span className="text-muted-foreground">{config[String(name)]?.label ?? name}</span>
                    <span className="ml-auto font-mono tabular-nums text-foreground">
                      {format(typeof value === "number" ? value : null)}
                    </span>
                  </>
                )}
              />
            }
          />
          {lines
            .filter((line) => line.band)
            .map((line) => (
              <Area
                key={`${line.key}_band`}
                dataKey={`${line.key}_band`}
                stroke="none"
                fill={line.color}
                fillOpacity={0.12}
                tooltipType="none"
                isAnimationActive={false}
                connectNulls={false}
              />
            ))}
          {lines.map((line) => (
            <Line
              key={line.key}
              dataKey={line.key}
              stroke={line.color}
              strokeWidth={2}
              dot={false}
              isAnimationActive={false}
              connectNulls={false}
            />
          ))}
        </ComposedChart>
      </ChartContainer>
    </figure>
  );
}
