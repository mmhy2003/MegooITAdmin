import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { formatTime } from "@/components/profile/profile-page";
import { MonitoringCard } from "@/components/servers/monitoring-card";
import type { Server } from "@/lib/servers";

const since = "2026-11-25T10:00:00Z";
const last_sample_at = "2026-11-25T10:05:00Z";

const LINUX: Server = {
  id: "s-1",
  name: "db-01",
  address: "db.example.com",
  port: 22,
  os: "linux",
  role: null,
  tags: [],
  group_id: "g-staging",
  group_name: "staging",
  connection_settings: { username: "deploy" },
  host_key: null,
  created_at: "2026-11-01T08:00:00Z",
  updated_at: "2026-11-02T09:30:00Z",
  can_manage: true,
  host_key_state: "pinned",
  host_key_fingerprint: "SHA256:abc",
  host_key_type: "ssh-ed25519",
  host_key_pinned_at: "2026-11-03T10:00:00Z",
  host_key_changed_at: null,
  host_key_offered: null,
  can_connect: true,
  can_view_logs: false,
  metrics_interval_seconds: 5,
  monitoring: null,
};

const value = (label: string) => screen.getByText(label).nextSibling;

describe("MonitoringCard", () => {
  it("shows a reachable server with its state, since when and sample interval", () => {
    render(<MonitoringCard server={{ ...LINUX, monitoring: { state: "reachable", reason: null, since, last_sample_at } }} />);
    expect(screen.getByRole("heading", { level: 3, name: "Monitoring" })).toBeInTheDocument();
    expect(value("Status")).toHaveTextContent("Reachable");
    expect(value("Since")).toHaveTextContent(formatTime(since));
    expect(screen.queryByText("Last sample")).toBeNull();
    expect(value("Sample interval")).toHaveTextContent("Every 5 seconds");
    expect(screen.queryByTestId("monitoring-reason")).toBeNull();
  });

  it("says every second for an interval of 1", () => {
    render(<MonitoringCard server={{ ...LINUX, metrics_interval_seconds: 1 }} />);
    expect(value("Sample interval")).toHaveTextContent("Every second");
  });

  it("shows an unreachable server's last sample, reason and advice", () => {
    render(
      <MonitoringCard
        server={{ ...LINUX, monitoring: { state: "unreachable", reason: "no_samples", since, last_sample_at } }}
      />,
    );
    expect(value("Status")).toHaveTextContent("Unreachable");
    expect(value("Last sample")).toHaveTextContent(formatTime(last_sample_at));
    expect(screen.getByText("No sample for 30 seconds.")).toBeInTheDocument();
    expect(screen.getByText("The server stopped sending samples. It may be overloaded or frozen.")).toBeInTheDocument();
  });

  it("says none yet when an unreachable server never sent a sample", () => {
    render(
      <MonitoringCard
        server={{ ...LINUX, monitoring: { state: "unreachable", reason: "no_samples", since, last_sample_at: null } }}
      />,
    );
    expect(value("Last sample")).toHaveTextContent("None yet");
  });

  it("shows a Windows server as not monitored, without a sample interval", () => {
    render(
      <MonitoringCard
        server={{
          ...LINUX,
          os: "windows",
          monitoring: { state: "not_monitored", reason: "not_an_ssh_server", since, last_sample_at: null },
        }}
      />,
    );
    expect(value("Status")).toHaveTextContent("Not monitored");
    expect(screen.getByText("Only Linux servers are monitored.")).toBeInTheDocument();
    expect(screen.queryByText("Sample interval")).toBeNull();
  });

  it("shows a server the collector has not checked yet", () => {
    render(<MonitoringCard server={LINUX} />);
    expect(value("Status")).toHaveTextContent("Not checked yet");
    expect(screen.queryByText("Since")).toBeNull();
    expect(screen.getByText("The collector has not looked at this server yet.")).toBeInTheDocument();
    expect(value("Sample interval")).toHaveTextContent("Every 5 seconds");
  });

  it("shows the badge but no reason it does not know", () => {
    render(
      <MonitoringCard
        server={{ ...LINUX, monitoring: { state: "unreachable", reason: "something_new", since, last_sample_at } }}
      />,
    );
    expect(value("Status")).toHaveTextContent("Unreachable");
    expect(screen.queryByTestId("monitoring-reason")).toBeNull();
  });
});
