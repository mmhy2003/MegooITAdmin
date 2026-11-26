import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { LiveBadge } from "@/components/metrics/live-badge";
import { Meter } from "@/components/metrics/meter";
import { PercentValue } from "@/components/metrics/percent-value";
import { ServerVitals } from "@/components/metrics/server-vitals";
import { Sparkline } from "@/components/metrics/sparkline";
import { emptyTrend, type Vitals } from "@/lib/metrics";

describe("PercentValue", () => {
  it("shows a normal value without a mark", () => {
    const { container } = render(<PercentValue value={79} />);
    expect(container).toHaveTextContent(/^79%$/);
    expect(container.firstChild).not.toHaveClass("text-amber-ink");
    expect(container.firstChild).not.toHaveClass("text-pink-ink");
  });

  it("marks a value from 80 as high, in amber", () => {
    const { container } = render(<PercentValue value={80} />);
    expect(container.firstChild).toHaveClass("text-amber-ink");
    expect(screen.getByText("▲")).toHaveAttribute("aria-hidden");
    expect(screen.getByText("high")).toHaveClass("sr-only");
    expect(container).toHaveTextContent("80%");
  });

  it("marks a value from 90 as very high, in pink", () => {
    const { container } = render(<PercentValue value={90} />);
    expect(container.firstChild).toHaveClass("text-pink-ink");
    expect(screen.getByText("▲")).toBeInTheDocument();
    expect(screen.getByText("very high")).toHaveClass("sr-only");
  });

  it("shows a dash for a missing value", () => {
    const { container } = render(<PercentValue value={null} />);
    expect(container).toHaveTextContent(/^—$/);
  });
});

describe("Meter", () => {
  it("clamps the fill to 100%", () => {
    const { container } = render(<Meter percent={120} />);
    const fill = container.querySelector("[data-slot=meter-fill]");
    expect(fill).toHaveStyle({ width: "100%" });
    expect(container.firstChild).toHaveAttribute("aria-hidden", "true");
  });

  it("clamps below zero and follows the tone", () => {
    const { container, rerender } = render(<Meter percent={-5} />);
    expect(container.querySelector("[data-slot=meter-fill]")).toHaveStyle({ width: "0%" });
    rerender(<Meter percent={50} />);
    expect(container.querySelector("[data-slot=meter-fill]")).toHaveClass("bg-cyan");
    rerender(<Meter percent={85} />);
    expect(container.querySelector("[data-slot=meter-fill]")).toHaveClass("bg-amber");
    rerender(<Meter percent={95} />);
    expect(container.querySelector("[data-slot=meter-fill]")).toHaveClass("bg-pink");
  });

  it("has no fill without a value", () => {
    const { container } = render(<Meter percent={null} />);
    expect(container.querySelector("[data-slot=meter-fill]")).toBeNull();
  });
});

describe("Sparkline", () => {
  it("breaks the line at a missing value", () => {
    render(<Sparkline values={[1, null, 3]} label="CPU, last 5 minutes" />);
    const svg = screen.getByRole("img", { name: "CPU, last 5 minutes" });
    expect(svg).toHaveAttribute("viewBox", "0 0 60 16");
    const path = svg.querySelector("path");
    expect(path).toHaveAttribute("stroke", "currentColor");
    expect(path?.getAttribute("d")?.match(/M/g)).toHaveLength(2);
  });

  it("draws no path when every value is missing", () => {
    render(<Sparkline values={[null, null]} label="Memory" />);
    expect(screen.getByRole("img", { name: "Memory" }).querySelector("path")).toBeNull();
  });
});

describe("LiveBadge", () => {
  it.each([
    ["connecting", "Connecting…"],
    ["live", "Live"],
    ["reconnecting", "Reconnecting…"],
    ["paused", "Paused"],
  ] as const)("shows %s as %s", (status, label) => {
    render(<LiveBadge status={status} />);
    const badge = screen.getByRole("status");
    expect(badge).toHaveTextContent(label);
    expect(badge).toHaveAttribute("data-variant", "outline");
  });

  it("puts a dot hidden from assistive technology on the live badge", () => {
    render(<LiveBadge status="live" />);
    expect(screen.getByRole("status").querySelector("[aria-hidden]")).toHaveClass("bg-cyan");
  });
});

const vitals: Vitals = {
  overview: {
    server_id: "s1",
    time: "2026-11-26T10:00:00Z",
    cpu: 42,
    mem: 55,
    load: 0.5,
    disk: { mount: "/var", percent: 91 },
    rx: 1536,
    tx: 2048,
  },
  trend: { ...emptyTrend(Date.parse("2026-11-26T10:00:00Z")), cpu: [10, 20, 42], mem: [50, null, 55] },
};

function item(label: string): HTMLElement {
  const term = screen.getByText(label, { selector: "dt" });
  return term.nextElementSibling as HTMLElement;
}

describe("ServerVitals", () => {
  it("shows each value of the newest sample", () => {
    render(<ServerVitals vitals={vitals} stale={false} />);
    expect(item("CPU")).toHaveTextContent("42%");
    expect(within(item("CPU")).getByRole("img", { name: "CPU, last 5 minutes" })).toBeInTheDocument();
    expect(item("Memory")).toHaveTextContent("55%");
    expect(within(item("Memory")).getByRole("img", { name: "Memory, last 5 minutes" })).toBeInTheDocument();
    const disk = item("Fullest filesystem");
    expect(disk).toHaveTextContent("/var");
    expect(disk).toHaveTextContent("91%");
    expect(within(disk).getByText("very high")).toBeInTheDocument();
    expect(item("Load")).toHaveTextContent("0.50");
    const network = item("Network");
    expect(network).toHaveTextContent("↓ 1.5 KiB/s");
    expect(network).toHaveTextContent("↑ 2.0 KiB/s");
    expect(within(network).getByText("received")).toHaveClass("sr-only");
    expect(within(network).getByText("sent")).toHaveClass("sr-only");
  });

  it.each([
    ["stale", vitals, true],
    ["missing", undefined, false],
  ] as const)("shows dashes and no meter fill when the values are %s", (_, v, stale) => {
    const { container } = render(<ServerVitals vitals={v} stale={stale} />);
    for (const label of ["CPU", "Memory", "Fullest filesystem", "Load"]) {
      expect(item(label)).toHaveTextContent(/^—$/);
    }
    expect(item("Network")).toHaveTextContent(/^↓ — received ↑ — sent$/);
    expect(container.querySelector("[data-slot=meter-fill]")).toBeNull();
    expect(container).not.toHaveTextContent("42%");
  });

  it("puts the items in one row in the strip layout", () => {
    const { container } = render(<ServerVitals vitals={vitals} stale={false} layout="strip" />);
    expect(container.querySelector("dl")).toHaveClass("flex");
  });
});
