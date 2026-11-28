import { act, fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { mockElementSize } from "@/__tests__/helpers/element-size";
import { LogList } from "@/components/logs/log-list";
import { clock } from "@/lib/logs/download";
import { compileFilter, type CompiledFilter } from "@/lib/logs/filter";
import type { LineRow, MarkerRow, Row } from "@/lib/logs/store";

const T0 = Date.parse("2026-11-28T09:05:01.123Z");

function line(seq: number, text = `line ${seq}`, extra: Partial<LineRow> = {}): LineRow {
  return {
    kind: "line", key: `a:0:${seq}`, source: "a", run: 0, seq, time: new Date(T0 + seq).toISOString(), ms: T0 + seq,
    text, plain: text, level: "none", unit: null, truncated: false, ...extra,
  };
}

function lines(count: number, from = 1): Row[] {
  return Array.from({ length: count }, (_, i) => line(from + i));
}

function marker(n: number, kind: MarkerRow["marker"], count = 0): MarkerRow {
  return { kind: "marker", key: `a:m${n}`, source: "a", ms: T0, marker: kind, count };
}

function list(rows: Row[], options: { wrap?: boolean; filter?: CompiledFilter | null } = {}) {
  return <LogList rows={rows} utc wrap={options.wrap ?? false} filter={options.filter ?? null} tags={null} label="Journal" />;
}

let restore: () => void;
beforeEach(() => {
  restore = mockElementSize();
});
afterEach(() => restore());

describe("LogList", () => {
  it("draws only the rows in sight", () => {
    const { container } = render(list(lines(1000)));
    const drawn = container.querySelectorAll("[data-index]").length;
    expect(drawn).toBeGreaterThan(0);
    expect(drawn).toBeLessThanOrEqual(60);
  });

  it("shows a row's time, level tag, ANSI colours and matches", () => {
    const text = "\x1b[31mboom\x1b[0m: disk failed";
    const row = line(7, text, { plain: "boom: disk failed", level: "error" });
    const filter = compileFilter("disk", false) as CompiledFilter;
    const { container } = render(list([row], { filter }));
    expect(screen.getByText(clock(row.ms, true))).toBeInTheDocument();
    const tag = screen.getByText("ERR");
    expect(tag).toHaveClass("log-level-error");
    expect(screen.getByText("boom")).toHaveClass("ansi-fg-1");
    const marks = container.querySelectorAll("mark.log-match");
    expect([...marks].map((m) => m.textContent)).toEqual(["disk"]);
  });

  it("writes the markers", () => {
    render(list([line(1), marker(1, "skipped", 1240), marker(2, "reconnected"), line(2)]));
    expect(screen.getByText("1,240 lines skipped")).toBeInTheDocument();
    expect(screen.getByText("Reconnected")).toBeInTheDocument();
  });

  it("keeps lines on one row unless wrap is on", () => {
    const { rerender } = render(list([line(1)]));
    expect(screen.getByText("line 1").closest("[data-log-line]")).toHaveClass("whitespace-pre");
    rerender(list([line(1)], { wrap: true }));
    expect(screen.getByText("line 1").closest("[data-log-line]")).toHaveClass("whitespace-pre-wrap");
  });

  it("pauses on scroll-up and counts the new lines until Jump to latest", async () => {
    const { rerender } = render(list(lines(50)));
    const scroller = screen.getByRole("log");
    act(() => {
      scroller.scrollTop = 100;
      fireEvent.scroll(scroller);
    });
    rerender(list(lines(53)));
    const jump = screen.getByRole("button", { name: "Jump to latest · 3 new" });
    await userEvent.click(jump);
    expect(screen.queryByRole("button", { name: /Jump to latest/ })).not.toBeInTheDocument();
  });

  it("says no count once the row seen at the pause is gone", () => {
    const { rerender } = render(list(lines(50)));
    const scroller = screen.getByRole("log");
    act(() => {
      scroller.scrollTop = 100;
      fireEvent.scroll(scroller);
    });
    rerender(list(lines(50, 60)));
    expect(screen.getByRole("button", { name: "Jump to latest" })).toBeInTheDocument();
  });

  it("forgets the wrapped heights when wrap goes off", () => {
    vi.spyOn(HTMLElement.prototype, "offsetHeight", "get").mockImplementation(function (this: HTMLElement) {
      if (this.hasAttribute("data-log-scroll")) return 400;
      return this.getAttribute("data-index") === "0" ? 60 : 20;
    });
    const { container, rerender } = render(list(lines(5), { wrap: true }));
    const offsets = () =>
      [...container.querySelectorAll<HTMLElement>("[data-index]")].map((el) => el.style.transform);
    expect(offsets()[1]).toBe("translateY(60px)");
    rerender(list(lines(5)));
    expect(offsets()).toEqual([0, 20, 40, 60, 80].map((y) => `translateY(${y}px)`));
  });

  it("keeps following within 24 px of the end", () => {
    const { rerender } = render(list(lines(50)));
    const scroller = screen.getByRole("log");
    act(() => {
      scroller.scrollTop = 1000 - 400 - 10;
      fireEvent.scroll(scroller);
    });
    rerender(list(lines(53)));
    expect(screen.queryByRole("button", { name: /Jump to latest/ })).not.toBeInTheDocument();
  });

  it("is a log region that does not announce each line", () => {
    render(list(lines(3)));
    const log = screen.getByRole("log");
    expect(log).toHaveAttribute("aria-live", "off");
    expect(log).toHaveAttribute("aria-label", "Journal");
  });
});
