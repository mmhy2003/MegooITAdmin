import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { MetricChart } from "@/components/servers/performance/metric-chart";
import type { ChartLine, Series } from "@/lib/metrics";

function series(metric: string): Series {
  return { metric, instance: "", time: ["2026-11-26T10:00:00Z"], avg: [1], min: [null], max: [null] };
}
const RX: ChartLine = { key: "rx", label: "Received", color: "var(--chart-1)", series: series("net.rx"), band: false };
const TX: ChartLine = { key: "tx", label: "Sent", color: "var(--chart-2)", series: series("net.tx"), band: false };

describe("MetricChart", () => {
  it("lists every line's label in a legend when there are two", () => {
    render(<MetricChart lines={[RX, TX]} stepMs={5_000} unit="rate" label="Network" />);
    const legend = screen.getByRole("list");
    expect(within(legend).getAllByRole("listitem").map((item) => item.textContent)).toEqual(["Received", "Sent"]);
  });

  it("has no legend for one line", () => {
    render(<MetricChart lines={[RX]} stepMs={5_000} unit="rate" label="Network" />);
    expect(screen.queryByRole("list")).not.toBeInTheDocument();
  });

  it("names the figure with its label", () => {
    render(<MetricChart lines={[RX]} stepMs={5_000} unit="rate" label="Network" />);
    expect(screen.getByRole("figure", { name: "Network" })).toBeInTheDocument();
  });

  it("dims the figure while it waits for a new range", () => {
    const { rerender } = render(<MetricChart lines={[RX]} stepMs={5_000} unit="rate" label="Network" />);
    expect(screen.getByRole("figure")).not.toHaveClass("opacity-50");
    rerender(<MetricChart lines={[RX]} stepMs={5_000} unit="rate" label="Network" dimmed />);
    expect(screen.getByRole("figure")).toHaveClass("opacity-50");
  });
});
