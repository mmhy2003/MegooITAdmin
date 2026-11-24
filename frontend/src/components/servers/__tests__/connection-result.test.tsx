import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ConnectionResult } from "@/components/servers/connection-result";
import { CONNECTION_REASONS } from "@/lib/auth/messages";
import type { ConnectionCheck, ConnectionReason, ConnectionTestResult } from "@/lib/servers";

const ALL_PASSED: ConnectionCheck[] = [
  { name: "host_key", status: "passed" },
  { name: "platform_key", status: "passed" },
  { name: "not_root", status: "passed" },
  { name: "not_in_docker_group", status: "passed" },
  { name: "in_log_groups", status: "passed" },
  { name: "sudo_checker", status: "passed" },
  { name: "sudo_limited", status: "passed" },
];

function checks() {
  return within(screen.getByRole("list", { name: "Checks" }));
}

describe("ConnectionResult", () => {
  it("shows a working connection with its seven passed checks", () => {
    render(<ConnectionResult result={{ ok: true, reason: null, checks: ALL_PASSED }} />);
    const status = screen.getByRole("status");
    expect(within(status).getByText("Connection works")).toBeInTheDocument();
    expect(checks().getAllByRole("listitem")).toHaveLength(7);
    expect(checks().getAllByText("Passed")).toHaveLength(7);
    expect(checks().getByText("The host key matches the pinned key")).toBeInTheDocument();
    expect(checks().getByText("The account is not in the docker group")).toBeInTheDocument();
    expect(checks().getByText("sudo allows only megoo-ctl")).toBeInTheDocument();
  });

  it.each(Object.keys(CONNECTION_REASONS) as ConnectionReason[])("shows the title and advice of %s", (reason) => {
    const result: ConnectionTestResult = {
      ok: false,
      reason,
      checks: ALL_PASSED.map((c, i) => ({ ...c, status: i === 0 ? "failed" : "not_run" })),
    };
    render(<ConnectionResult result={result} />);
    const status = screen.getByRole("status");
    expect(within(status).getByText(CONNECTION_REASONS[reason].title)).toBeInTheDocument();
    expect(within(status).getByText(CONNECTION_REASONS[reason].advice)).toBeInTheDocument();
    expect(screen.queryByText("Connection works")).not.toBeInTheDocument();
  });

  it("marks a changed host key as failed and the other checks as not checked", () => {
    render(
      <ConnectionResult
        result={{
          ok: false,
          reason: "host_key_changed",
          checks: [
            { name: "host_key", status: "failed" },
            { name: "platform_key", status: "not_run" },
            { name: "not_root", status: "not_run" },
            { name: "not_in_docker_group", status: "not_run" },
            { name: "in_log_groups", status: "not_run" },
            { name: "sudo_checker", status: "not_run" },
            { name: "sudo_limited", status: "not_run" },
          ],
        }}
      />,
    );
    expect(checks().getAllByText("Failed")).toHaveLength(1);
    expect(checks().getAllByText("Not checked")).toHaveLength(6);
    expect(checks().queryByText("Passed")).not.toBeInTheDocument();
  });

  it("tells how to fix a refused key", () => {
    render(<ConnectionResult result={{ ok: false, reason: "key_refused", checks: ALL_PASSED }} />);
    expect(
      within(screen.getByRole("status")).getByText(
        "Run the setup script on the server with the platform's key (see Platform access), and check that --from holds the address the server sees MegooITAdmin connect from.",
      ),
    ).toBeInTheDocument();
  });

  it("gives no advice when the connection works", () => {
    render(<ConnectionResult result={{ ok: true, reason: null, checks: ALL_PASSED }} />);
    for (const { advice } of Object.values(CONNECTION_REASONS)) {
      expect(screen.queryByText(advice)).not.toBeInTheDocument();
    }
  });
});
