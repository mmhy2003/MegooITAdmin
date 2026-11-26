import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { CheckCard } from "@/components/servers/checks/check-card";
import type { CheckState, ServerCheck } from "@/lib/checks";

const now = new Date("2026-11-25T12:00:00Z");

const SERVICES: ServerCheck<"services"> = {
  kind: "services",
  status: "ok",
  checked_at: "2026-11-25T11:58:00Z",
  every_seconds: 60,
  data: { total: 3, running: 3, failed: 0, failed_units: [] },
  data_at: "2026-11-25T11:58:00Z",
};

function renderCard(check: ServerCheck, footnote?: string) {
  return render(
    <CheckCard title="Services" check={check} now={now} okBadge={<span>All running</span>} footnote={footnote}>
      <p>The result</p>
    </CheckCard>,
  );
}

describe("CheckCard", () => {
  it("shows its title, the ok badge and the result when the check is ok", () => {
    renderCard(SERVICES);
    expect(screen.getByRole("heading", { level: 3, name: "Services" })).toBeInTheDocument();
    expect(screen.getByText("All running")).toBeInTheDocument();
    expect(screen.getByText("The result")).toBeInTheDocument();
    expect(screen.queryByText(/Showing the result from/)).not.toBeInTheDocument();
  });

  it.each<[CheckState, string, string, string]>([
    ["not_checked", "Not checked yet", "The collector has not run this check yet.", "text-muted-foreground"],
    ["not_available", "Not available", "systemd is not running on this server.", "text-muted-foreground"],
    [
      "denied",
      "Not allowed",
      "sudo refused megoo-ctl on this server. Run megoo-setup.sh on it again (Platform access card).",
      "text-amber-ink",
    ],
    ["timeout", "Could not be checked", "The check took too long.", "text-amber-ink"],
    ["failed", "Could not be checked", "The check failed or printed something unexpected.", "text-amber-ink"],
  ])("shows the %s state with its badge and text", (status, badge, text, tone) => {
    renderCard({ ...SERVICES, status, data: null, data_at: null });
    expect(screen.getByText(badge)).toHaveClass(tone);
    expect(screen.getByText(text)).toBeInTheDocument();
    expect(screen.queryByText("All running")).not.toBeInTheDocument();
    expect(screen.queryByText("The result")).not.toBeInTheDocument();
  });

  it("draws the not checked badge with a dashed border", () => {
    renderCard({ ...SERVICES, status: "not_checked", checked_at: null, data: null, data_at: null });
    expect(screen.getByText("Not checked yet")).toHaveClass("border-dashed");
    expect(screen.getByTestId("check-footer")).toHaveTextContent("");
  });

  it("keeps showing the older result of a failed run and says how old it is", () => {
    renderCard({ ...SERVICES, status: "failed", data_at: "2026-11-25T11:50:00Z" });
    expect(screen.getByText("The result")).toBeInTheDocument();
    expect(screen.getByText("The check failed or printed something unexpected.")).toBeInTheDocument();
    expect(screen.getByText("Showing the result from 10 minutes ago.")).toBeInTheDocument();
  });

  it("says when the check last ran and how often it runs", () => {
    renderCard(SERVICES);
    const footer = screen.getByTestId("check-footer");
    expect(footer).toHaveTextContent("Checked 2 minutes ago · every minute");
    expect(footer.querySelector(".text-amber-ink")).toBeNull();
  });

  it("marks an old result in amber", () => {
    renderCard({ ...SERVICES, checked_at: "2026-11-25T11:56:00Z" });
    const text = screen.getByText("Last checked 4 minutes ago · every minute");
    expect(text).toHaveClass("text-amber-ink");
  });

  it("shows its footnote under the footer", () => {
    renderCard(SERVICES, "Names that were tried are not kept.");
    expect(screen.getByText("Names that were tried are not kept.")).toBeInTheDocument();
  });
});
