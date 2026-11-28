"use client";

import { memo, type ReactNode } from "react";
import { parseAnsi, segmentClass } from "@/lib/logs/ansi";
import { clock } from "@/lib/logs/download";
import type { CompiledFilter } from "@/lib/logs/filter";
import { LEVEL_TAGS } from "@/lib/logs/levels";
import type { LineRow, Row } from "@/lib/logs/store";
import { cn } from "@/lib/utils";

type Tag = { text: string; tone: number };

/** The styled segments of a line, with the filter's ranges marked. ANSI is parsed here, when a row is drawn. */
function body(row: LineRow, filter: CompiledFilter | null): ReactNode[] {
  const ranges = filter ? filter.ranges(row.plain) : [];
  const nodes: ReactNode[] = [];
  let at = 0;
  let r = 0;
  parseAnsi(row.text).forEach((segment, s) => {
    const end = at + segment.text.length;
    const pieces: ReactNode[] = [];
    let from = at;
    while (from < end) {
      while (r < ranges.length && ranges[r][1] <= from) r++;
      const range = ranges[r];
      if (range && range[0] <= from) {
        const to = Math.min(end, range[1]);
        pieces.push(<mark key={from} className="log-match">{segment.text.slice(from - at, to - at)}</mark>);
        from = to;
      } else {
        const to = Math.min(end, range ? range[0] : end);
        pieces.push(segment.text.slice(from - at, to - at));
        from = to;
      }
    }
    const style = segmentClass(segment);
    nodes.push(style ? <span key={s} className={style}>{pieces}</span> : <span key={s}>{pieces}</span>);
    at = end;
  });
  return nodes;
}

/** One row of a pane: a line with its time, tags and text, or a marker. */
export const LogLine = memo(function LogLine({ row, utc, wrap, filter, tag }: {
  row: Row;
  utc: boolean;
  wrap: boolean;
  filter: CompiledFilter | null;
  tag: Tag | null;
}) {
  const tagNode = tag && <span className={cn("shrink-0", `log-tag-${tag.tone}`)}>{tag.text}</span>;
  if (row.kind === "marker") {
    return (
      <div data-log-line className="flex gap-2 px-3 font-mono text-xs leading-5 text-muted-foreground italic whitespace-pre">
        {tagNode}
        <span>{row.marker === "skipped" ? `${row.count.toLocaleString("en-US")} lines skipped` : "Reconnected"}</span>
      </div>
    );
  }
  const level = LEVEL_TAGS[row.level];
  return (
    <div
      data-log-line
      className={cn("flex gap-2 px-3 font-mono text-xs leading-5", wrap ? "whitespace-pre-wrap break-all" : "whitespace-pre")}
    >
      <span className="shrink-0 text-muted-foreground">{clock(row.ms, utc)}</span>
      {tagNode}
      <span className={cn("w-7 shrink-0", level && `log-level-${row.level}`)}>{level}</span>
      <span className="min-w-0">
        {body(row, filter)}
        {row.truncated && "…"}
      </span>
    </div>
  );
});
