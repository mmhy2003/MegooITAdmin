"use client";

import { useVirtualizer } from "@tanstack/react-virtual";
import { useLayoutEffect, useRef, useState } from "react";
import { LogLine } from "@/components/logs/log-line";
import { Button } from "@/components/ui/button";
import type { CompiledFilter } from "@/lib/logs/filter";
import type { Row } from "@/lib/logs/store";
import { cn } from "@/lib/utils";

/** Within this many pixels of the end, the list follows new rows; further up, it is paused. */
const END_THRESHOLD = 24;
const ROW_HEIGHT = 20;

/**
 * How many rows come after the row with `key`, looking from the end; every row when the list was empty (null). A
 * key that is gone (trimmed by the cap, or hidden by a filter) gives 0: the count is no longer known.
 */
function rowsAfter(rows: Row[], key: string | null): number {
  if (key === null) return rows.length;
  for (let i = rows.length - 1; i >= 0; i--) {
    if (rows[i].key === key) return rows.length - 1 - i;
  }
  return 0;
}

/**
 * The virtualised rows of a pane. It follows appended rows while it is scrolled to the end, and pauses when the
 * person scrolls up: "Jump to latest" then counts the rows that came since. With wrap on, rows are measured.
 */
export function LogList({ rows, utc, wrap, filter, tags, label }: {
  rows: Row[];
  utc: boolean;
  wrap: boolean;
  filter: CompiledFilter | null;
  tags: Map<string, { text: string; tone: number }> | null;
  label: string;
}) {
  const scrollRef = useRef<HTMLDivElement>(null);
  // The key of the last row when the list paused; undefined while it follows.
  const [pausedAt, setPausedAt] = useState<string | null | undefined>(undefined);
  // The React Compiler is off, and the virtualizer is used only in this component, never passed to a memoised one.
  // eslint-disable-next-line react-hooks/incompatible-library
  const virtualizer = useVirtualizer({
    count: rows.length,
    getScrollElement: () => scrollRef.current,
    estimateSize: () => ROW_HEIGHT,
    getItemKey: (i) => rows[i].key,
    anchorTo: "end",
    followOnAppend: true,
    scrollEndThreshold: END_THRESHOLD,
    overscan: 20,
  });
  const paused = pausedAt !== undefined;

  // Measured heights stay in the virtualizer's cache: drop them when wrap changes, so rows go back to their estimate.
  useLayoutEffect(() => {
    virtualizer.measure();
  }, [virtualizer, wrap]);

  function onScroll() {
    const el = scrollRef.current;
    if (!el) return;
    const away = el.scrollHeight - el.scrollTop - el.clientHeight > END_THRESHOLD;
    if (away && !paused) setPausedAt(rows.at(-1)?.key ?? null);
    else if (!away && paused) setPausedAt(undefined);
  }

  function jump() {
    setPausedAt(undefined);
    if (rows.length > 0) virtualizer.scrollToIndex(rows.length - 1, { align: "end" });
  }

  const fresh = paused ? rowsAfter(rows, pausedAt) : 0;
  return (
    <div className="relative min-h-0 flex-1">
      <div
        ref={scrollRef}
        data-log-scroll
        role="log"
        aria-live="off"
        aria-label={label}
        tabIndex={0}
        onScroll={onScroll}
        className="h-full overflow-auto outline-none focus-visible:ring-[3px] focus-visible:ring-ring/50"
      >
        <div className="relative min-w-full" style={{ height: `${virtualizer.getTotalSize()}px` }}>
          {virtualizer.getVirtualItems().map((item) => {
            const row = rows[item.index];
            return (
              <div
                key={item.key}
                data-index={item.index}
                ref={wrap ? virtualizer.measureElement : undefined}
                className={cn("absolute top-0 left-0 min-w-full", wrap ? "w-full" : "h-5 w-max")}
                style={{ transform: `translateY(${item.start}px)` }}
              >
                <LogLine row={row} utc={utc} wrap={wrap} filter={filter} tag={tags?.get(row.source) ?? null} />
              </div>
            );
          })}
        </div>
      </div>
      {paused && (
        <Button size="sm" className="absolute right-4 bottom-3 shadow-md" onClick={jump}>
          {fresh > 0 ? `Jump to latest · ${fresh.toLocaleString("en-US")} new` : "Jump to latest"}
        </Button>
      )}
    </div>
  );
}
