import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { UpdatesCard } from "@/components/servers/checks/updates-card";
import type { ServerCheck, UpdatesData } from "@/lib/checks";

const now = new Date("2026-11-25T12:00:00Z");

const APT: UpdatesData = {
  manager: "apt",
  pending: 2,
  security: 1,
  reboot_required: false,
  lists_refreshed_at: "2026-11-25T09:00:00Z",
};

function check(data: UpdatesData): ServerCheck<"updates"> {
  return {
    kind: "updates",
    status: "ok",
    checked_at: "2026-11-25T11:30:00Z",
    every_seconds: 3600,
    data,
    data_at: "2026-11-25T11:30:00Z",
  };
}

describe("UpdatesCard", () => {
  it("shows the pending and the security updates, the security line in amber", () => {
    render(<UpdatesCard check={check(APT)} now={now} />);
    expect(screen.getByRole("heading", { level: 3, name: "Updates" })).toBeInTheDocument();
    expect(screen.getByText("2 pending updates")).toBeInTheDocument();
    expect(screen.getByText("1 security updates")).toHaveClass("text-amber-ink");
    expect(screen.getByText("Package lists refreshed 3 hours ago")).toBeInTheDocument();
    expect(screen.getByText("Updates", { selector: "[data-slot=badge]" })).toHaveClass("text-amber-ink");
    expect(screen.queryByText("Restart required")).not.toBeInTheDocument();
  });

  it("says a restart is required", () => {
    render(<UpdatesCard check={check({ ...APT, reboot_required: true })} now={now} />);
    expect(screen.getByText("Restart required")).toHaveClass("text-amber-ink");
  });

  it("leaves the security line out when dnf cannot tell", () => {
    render(
      <UpdatesCard
        check={check({ manager: "dnf", pending: 2, security: null, reboot_required: null, lists_refreshed_at: null })}
        now={now}
      />,
    );
    expect(screen.getByText("2 pending updates")).toBeInTheDocument();
    expect(screen.queryByText(/security updates/)).not.toBeInTheDocument();
    expect(screen.queryByText(/Package lists refreshed/)).not.toBeInTheDocument();
  });

  it("says the server is up to date", () => {
    render(<UpdatesCard check={check({ ...APT, pending: 0, security: 0 })} now={now} />);
    const texts = screen.getAllByText("Up to date");
    expect(texts).toHaveLength(2);
    expect(texts.some((el) => el.classList.contains("text-green-ink"))).toBe(true);
    expect(screen.queryByText(/security updates/)).not.toBeInTheDocument();
  });
});
