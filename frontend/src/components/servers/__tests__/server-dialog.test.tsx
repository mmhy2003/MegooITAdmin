import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ServerDialog } from "@/components/servers/server-dialog";
import type { ServerGroup } from "@/lib/access";
import { ApiError, apiFetch } from "@/lib/api";
import type { Server } from "@/lib/servers";

vi.mock("@/lib/api", async (orig) => ({ ...(await orig<typeof import("@/lib/api")>()), apiFetch: vi.fn() }));
vi.mock("@/lib/auth/navigate");

function group(id: string, name: string): ServerGroup {
  return {
    id,
    name,
    description: null,
    created_at: "2026-11-01T00:00:00Z",
    member_count: 1,
    server_count: 0,
    can_manage: true,
  };
}

const GROUPS = [group("g-production", "production"), group("g-staging", "staging")];

const WEB: Server = {
  id: "s-1",
  name: "web-01",
  address: "10.0.0.5",
  port: 22,
  os: "linux",
  role: "web",
  tags: ["nginx"],
  group_id: "g-staging",
  group_name: "staging",
  connection_settings: { username: "megoo" },
  host_key: null,
  created_at: "2026-11-01T00:00:00Z",
  updated_at: "2026-11-01T00:00:00Z",
  can_manage: true,
  host_key_state: "not_pinned",
  host_key_fingerprint: null,
  host_key_type: null,
  host_key_pinned_at: null,
  host_key_changed_at: null,
  host_key_offered: null,
  can_connect: true,
  can_view_logs: false,
  metrics_interval_seconds: 5,
  monitoring: null,
};

beforeEach(() => {
  vi.mocked(apiFetch).mockReset();
});

function renderDialog(props: Partial<Parameters<typeof ServerDialog>[0]> = {}) {
  const onSaved = vi.fn();
  const onStale = vi.fn();
  render(
    <ServerDialog
      server={null}
      groups={GROUPS}
      defaultGroupId="g-staging"
      tags={["db", "web"]}
      open
      onOpenChange={vi.fn()}
      onSaved={onSaved}
      onStale={onStale}
      {...props}
    />,
  );
  return { onSaved, onStale, user: userEvent.setup() };
}

describe("ServerDialog", () => {
  it("registers a server with the defaults", async () => {
    const saved = { ...WEB, id: "s-2" };
    vi.mocked(apiFetch).mockResolvedValue(saved);
    const { user, onSaved } = renderDialog();

    expect(screen.getByRole("heading", { name: "Register a server" })).toBeInTheDocument();
    await user.type(screen.getByLabelText("Name"), "web-02");
    await user.type(screen.getByLabelText("Address"), "10.0.0.6");
    await user.type(screen.getByLabelText("Tags"), "web{Enter}");
    await user.click(screen.getByRole("button", { name: "Register server" }));

    expect(apiFetch).toHaveBeenCalledWith("/servers", {
      method: "POST",
      body: {
        name: "web-02",
        address: "10.0.0.6",
        group_id: "g-staging",
        os: "linux",
        port: 22,
        metrics_interval_seconds: 5,
        role: null,
        tags: ["web"],
        connection_settings: { username: "megoo" },
      },
    });
    expect(onSaved).toHaveBeenCalledWith(saved);
  });

  it("starts in the first group without a default one", () => {
    renderDialog({ defaultGroupId: null });
    expect(screen.getByRole("combobox", { name: "Server group" })).toHaveTextContent("production");
  });

  it("follows the operating system with the port until the port is edited", async () => {
    const { user } = renderDialog();
    const port = screen.getByLabelText("Port");

    expect(port).toHaveValue(22);
    await user.click(screen.getByRole("radio", { name: "Windows" }));
    expect(port).toHaveValue(3389);

    await user.clear(port);
    await user.type(port, "2222");
    await user.click(screen.getByRole("radio", { name: "Linux" }));
    expect(port).toHaveValue(2222);
  });

  it("saves only the changed field of a server", async () => {
    vi.mocked(apiFetch).mockResolvedValue({ ...WEB, port: 2200 });
    const { user, onSaved } = renderDialog({ server: WEB });

    expect(screen.getByRole("heading", { name: "Edit web-01" })).toBeInTheDocument();
    const save = screen.getByRole("button", { name: "Save" });
    expect(save).toBeDisabled();

    await user.clear(screen.getByLabelText("Port"));
    await user.type(screen.getByLabelText("Port"), "2200");
    expect(save).toBeEnabled();
    await user.click(save);

    expect(apiFetch).toHaveBeenCalledWith("/servers/s-1", { method: "PATCH", body: { port: 2200 } });
    expect(onSaved).toHaveBeenCalledWith({ ...WEB, port: 2200 });
  });

  it("does not move the port of a saved server when its OS changes", async () => {
    const { user } = renderDialog({ server: { ...WEB, port: 2222 } });

    await user.click(screen.getByRole("radio", { name: "Windows" }));
    expect(screen.getByLabelText("Port")).toHaveValue(2222);
  });

  it("registers a chosen sample interval", async () => {
    vi.mocked(apiFetch).mockResolvedValue({ ...WEB, id: "s-2" });
    const { user } = renderDialog();
    const interval = screen.getByLabelText("Sample interval");

    expect(interval).toHaveValue(5);
    expect(interval).toHaveAttribute("min", "1");
    expect(interval).toHaveAttribute("max", "10");
    expect(interval).toHaveAttribute("step", "1");
    expect(interval).toBeRequired();
    expect(interval).toHaveAccessibleDescription("How often its metrics are read: 1 to 10 seconds.");
    expect(screen.getByText("seconds")).toBeInTheDocument();

    await user.clear(interval);
    await user.type(interval, "2");
    await user.type(screen.getByLabelText("Name"), "web-02");
    await user.type(screen.getByLabelText("Address"), "10.0.0.6");
    await user.click(screen.getByRole("button", { name: "Register server" }));

    expect(apiFetch).toHaveBeenCalledWith(
      "/servers",
      expect.objectContaining({ method: "POST", body: expect.objectContaining({ metrics_interval_seconds: 2 }) }),
    );
  });

  it("saves only the changed interval", async () => {
    vi.mocked(apiFetch).mockResolvedValue({ ...WEB, metrics_interval_seconds: 10 });
    const { user } = renderDialog({ server: WEB });
    const interval = screen.getByLabelText("Sample interval");

    expect(interval).toHaveValue(5);
    await user.clear(interval);
    await user.type(interval, "10");
    await user.click(screen.getByRole("button", { name: "Save" }));

    expect(apiFetch).toHaveBeenCalledWith("/servers/s-1", { method: "PATCH", body: { metrics_interval_seconds: 10 } });
  });

  it("copies a saved interval", () => {
    renderDialog({ server: { ...WEB, metrics_interval_seconds: 3 } });
    expect(screen.getByLabelText("Sample interval")).toHaveValue(3);
  });

  it("hides the interval for Windows and sends its saved value", async () => {
    vi.mocked(apiFetch).mockResolvedValue({ ...WEB, id: "s-2" });
    const { user } = renderDialog();

    await user.clear(screen.getByLabelText("Sample interval"));
    await user.type(screen.getByLabelText("Sample interval"), "8");
    await user.click(screen.getByRole("radio", { name: "Windows" }));
    expect(screen.queryByLabelText("Sample interval")).toBeNull();

    await user.type(screen.getByLabelText("Name"), "win-01");
    await user.type(screen.getByLabelText("Address"), "10.0.0.7");
    await user.click(screen.getByRole("button", { name: "Register server" }));
    expect(apiFetch).toHaveBeenCalledWith(
      "/servers",
      expect.objectContaining({
        body: expect.objectContaining({ metrics_interval_seconds: 5, os: "windows" }),
      }),
    );

    await user.click(screen.getByRole("radio", { name: "Linux" }));
    expect(screen.getByLabelText("Sample interval")).toHaveValue(5);
  });

  it("an edited Windows switch sends no interval change", async () => {
    vi.mocked(apiFetch).mockResolvedValue({ ...WEB, os: "windows", port: 3389 });
    const { user } = renderDialog({ server: WEB });

    await user.clear(screen.getByLabelText("Sample interval"));
    await user.type(screen.getByLabelText("Sample interval"), "8");
    await user.click(screen.getByRole("radio", { name: "Windows" }));
    await user.click(screen.getByRole("button", { name: "Save" }));

    expect(apiFetch).toHaveBeenCalledWith("/servers/s-1", { method: "PATCH", body: { os: "windows", port: 3389 } });
  });

  it("shows no interval for a Windows server", () => {
    renderDialog({ server: { ...WEB, os: "windows", port: 3389 } });
    expect(screen.queryByLabelText("Sample interval")).toBeNull();
  });

  it("says what moving the server to another group means", async () => {
    const { user } = renderDialog({ server: WEB });
    const notice =
      "Moving web-01 to production changes who sees it: the people of staging lose it and those of production get it.";
    expect(screen.queryByText(notice)).not.toBeInTheDocument();

    await user.click(screen.getByRole("combobox", { name: "Server group" }));
    await user.click(await screen.findByRole("option", { name: "production" }));

    expect(screen.getByText(notice)).toBeInTheDocument();
  });

  it("shows a taken name", async () => {
    vi.mocked(apiFetch).mockRejectedValue(new ApiError(409, "server_name_taken"));
    const { user, onSaved, onStale } = renderDialog();

    await user.type(screen.getByLabelText("Name"), "web-01");
    await user.type(screen.getByLabelText("Address"), "10.0.0.6");
    await user.click(screen.getByRole("button", { name: "Register server" }));

    expect(await screen.findByText("A server with this name exists already.")).toBeInTheDocument();
    expect(onSaved).not.toHaveBeenCalled();
    expect(onStale).not.toHaveBeenCalled();
  });

  it("reports a refusal as stale", async () => {
    vi.mocked(apiFetch).mockRejectedValue(new ApiError(403, "forbidden"));
    const { user, onSaved, onStale } = renderDialog({ server: WEB });

    await user.clear(screen.getByLabelText("Role"));
    await user.click(screen.getByRole("button", { name: "Save" }));

    expect(apiFetch).toHaveBeenCalledWith("/servers/s-1", { method: "PATCH", body: { role: null } });
    expect(await screen.findByText("You do not have the rights to do this.")).toBeInTheDocument();
    expect(onStale).toHaveBeenCalled();
    expect(onSaved).not.toHaveBeenCalled();
  });
});
