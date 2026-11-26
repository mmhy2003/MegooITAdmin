import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { LoginsCard } from "@/components/servers/checks/logins-card";
import type { LoginsData, ServerCheck } from "@/lib/checks";

const now = new Date("2026-11-25T12:00:00Z");

function check(data: LoginsData): ServerCheck<"logins"> {
  return {
    kind: "logins",
    status: "ok",
    checked_at: "2026-11-25T11:58:00Z",
    every_seconds: 300,
    data,
    data_at: "2026-11-25T11:58:00Z",
  };
}

const FOOTNOTE = "Counts failed passwords and unknown accounts. Names that were tried are not kept.";

describe("LoginsCard", () => {
  it("counts the failed sign-ins and lists the top sources", () => {
    const data: LoginsData = {
      failed_24h: 4,
      top_sources: [
        { address: "203.0.113.7", count: 3 },
        { address: "2001:db8::1", count: 1 },
      ],
    };
    render(<LoginsCard check={check(data)} now={now} />);
    expect(screen.getByRole("heading", { level: 3, name: "Failed sign-ins" })).toBeInTheDocument();
    expect(screen.getByText("4 failed SSH sign-ins in the last 24 hours")).toBeInTheDocument();
    expect(screen.getByText("203.0.113.7")).toHaveClass("font-mono");
    expect(screen.getByText("3 attempts")).toBeInTheDocument();
    expect(screen.getByText("2001:db8::1")).toHaveClass("font-mono");
    expect(screen.getByText("1 attempts")).toBeInTheDocument();
    expect(screen.getByText("4 failed", { selector: "[data-slot=badge]" })).toHaveClass("text-amber-ink");
    expect(screen.getByText(FOOTNOTE)).toBeInTheDocument();
  });

  it("says when there were none", () => {
    render(<LoginsCard check={check({ failed_24h: 0, top_sources: [] })} now={now} />);
    expect(screen.getByText("No failed SSH sign-ins in the last 24 hours")).toBeInTheDocument();
    expect(screen.getByText("None", { selector: "[data-slot=badge]" })).toHaveClass("text-green-ink");
    expect(screen.getByText(FOOTNOTE)).toBeInTheDocument();
  });
});
