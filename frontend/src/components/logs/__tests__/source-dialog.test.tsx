import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { server } from "@/components/dashboard/__tests__/fixtures";
import { SourceDialog } from "@/components/logs/source-dialog";
import { apiFetch } from "@/lib/api";
import type { Container } from "@/lib/checks";
import type { LogSource } from "@/lib/logs/sources";

vi.mock("@/lib/api", async (orig) => ({ ...(await orig<typeof import("@/lib/api")>()), apiFetch: vi.fn() }));
vi.mock("@/lib/auth/navigate");

const A = "6f1c2a8e-4b3d-4e5f-9a0b-1c2d3e4f5a6b";
const B = "0a1b2c3d-4e5f-4a6b-8c7d-9e0f1a2b3c4d";
const WEB_01 = server("web-01", null, { id: A, can_view_logs: true, group_id: "g1", group_name: "Production" });
const DB_01 = server("db-01", null, { id: B, can_view_logs: true, group_id: "g2", group_name: "Staging" });
const WIN_01 = server("win-01", null, { id: "s-win", os: "windows", can_view_logs: true, group_name: "Production" });
const BLIND = server("blind-01", null, { id: "s-blind", can_view_logs: false, group_name: "Production" });
const SERVERS = [WEB_01, DB_01, WIN_01, BLIND];

const pattern = (id: string, text: string) => ({ id, pattern: text, created_at: "2026-11-01T00:00:00Z" });
let allowlist = { can_manage: true, patterns: [pattern("p1", "/var/log/nginx/*.log"), pattern("p2", "/var/log/syslog")] };

function listed(container_id: string, name: string, project: string | null, state = "running"): Container {
  return {
    container_id, runtime: "docker", name, image: "nginx:1.27", compose_project: project, compose_service: null,
    state, status: "Up 2 hours", first_seen_at: "2026-11-28T08:00:00Z", last_seen_at: "2026-11-28T09:00:00Z",
  };
}

const CONTAINERS = [
  listed("3f2a9b8c7d6e", "web", "shop"),
  listed("9e8d7c6b5a4f", "db", "shop", "exited"),
  listed("1a2b3c4d5e6f", "cron", null),
];

beforeEach(() => {
  vi.mocked(apiFetch).mockReset();
  allowlist = { can_manage: true, patterns: [pattern("p1", "/var/log/nginx/*.log"), pattern("p2", "/var/log/syslog")] };
  vi.mocked(apiFetch).mockImplementation(async (path: string) => {
    if (path === "/server-groups/g1/log-allowlist") return allowlist;
    if (path === `/servers/${A}/containers`) return CONTAINERS;
    throw new Error(`unexpected ${path}`);
  });
});

function renderDialog(props: Partial<Parameters<typeof SourceDialog>[0]> = {}) {
  const onAdd = vi.fn();
  const onOpenChange = vi.fn();
  render(
    <SourceDialog open onOpenChange={onOpenChange} servers={SERVERS} serverId={A} current={[]} onAdd={onAdd}
      {...props} />,
  );
  return { onAdd, onOpenChange, user: userEvent.setup() };
}

type User = ReturnType<typeof userEvent.setup>;

async function choose(user: User, select: string, option: string) {
  await user.click(screen.getByRole("combobox", { name: select }));
  await user.click(await screen.findByRole("option", { name: option }));
}

const add = () => screen.getByRole("button", { name: "Add" });

function journal(extra: Partial<Extract<LogSource, { kind: "journal" }>> = {}): LogSource {
  return { kind: "journal", server_id: A, unit: null, priority: null, this_boot: false, ...extra };
}

describe("SourceDialog", () => {
  it("offers only the Linux servers with View logs, by group", async () => {
    const { user } = renderDialog({ serverId: undefined });
    await user.click(screen.getByRole("combobox", { name: "Server" }));
    const production = within(await screen.findByRole("group", { name: "Production" }));
    expect(production.getAllByRole("option").map((o) => o.textContent)).toEqual(["web-01"]);
    const staging = within(screen.getByRole("group", { name: "Staging" }));
    expect(staging.getAllByRole("option").map((o) => o.textContent)).toEqual(["db-01"]);
    expect(screen.getAllByRole("option")).toHaveLength(2);
  });

  it("keeps the server fixed when it is given", () => {
    renderDialog();
    expect(screen.queryByRole("combobox", { name: "Server" })).not.toBeInTheDocument();
    expect(screen.getByText("web-01")).toBeInTheDocument();
  });

  it("asks for a server before it adds", async () => {
    const { user, onAdd } = renderDialog({ serverId: undefined });
    expect(add()).toBeDisabled();
    await choose(user, "Server", "db-01");
    await user.click(add());
    expect(onAdd).toHaveBeenCalledWith([{ ...journal(), server_id: B }]);
  });

  describe("Journal", () => {
    it("refuses an invalid unit", async () => {
      const { user, onAdd } = renderDialog();
      await user.type(screen.getByLabelText("Unit"), "nginx service");
      expect(screen.getByText("Not a valid unit name")).toBeInTheDocument();
      expect(screen.getByLabelText("Unit")).toHaveAttribute("aria-invalid", "true");
      expect(add()).toBeDisabled();
      expect(onAdd).not.toHaveBeenCalled();
    });

    it("adds the whole journal by default, and closes", async () => {
      const { user, onAdd, onOpenChange } = renderDialog();
      await user.click(add());
      expect(onAdd).toHaveBeenCalledWith([journal()]);
      expect(onOpenChange).toHaveBeenCalledWith(false);
    });

    it("adds a unit, a priority and this boot only", async () => {
      const { user, onAdd } = renderDialog();
      await user.type(screen.getByLabelText("Unit"), "nginx.service");
      await user.click(screen.getByRole("combobox", { name: "Priority" }));
      expect(screen.getAllByRole("option").map((o) => o.textContent)).toEqual([
        "Any", "emerg and worse", "alert and worse", "crit and worse", "err and worse", "warning and worse",
        "notice and worse", "info and worse", "debug and worse",
      ]);
      await user.click(screen.getByRole("option", { name: "warning and worse" }));
      await user.click(screen.getByRole("checkbox", { name: "This boot only" }));
      await user.click(add());
      expect(onAdd).toHaveBeenCalledWith([journal({ unit: "nginx.service", priority: "warning", this_boot: true })]);
    });
  });

  describe("File", () => {
    it("shows the group's patterns below the path", async () => {
      const { user } = renderDialog();
      await user.click(screen.getByRole("radio", { name: "File" }));
      const list = within(await screen.findByRole("list", { name: "Patterns of Production" }));
      expect(list.getAllByRole("listitem").map((i) => i.textContent)).toEqual(["/var/log/nginx/*.log", "/var/log/syslog"]);
      expect(apiFetch).toHaveBeenCalledWith("/server-groups/g1/log-allowlist");
    });

    it("offers a pattern without a wildcard as the person types", async () => {
      const { user, onAdd } = renderDialog();
      await user.click(screen.getByRole("radio", { name: "File" }));
      await screen.findByRole("list", { name: "Patterns of Production" });
      await user.type(screen.getByLabelText("Path"), "/var/log/s");
      expect(screen.queryByRole("button", { name: "/var/log/nginx/*.log" })).not.toBeInTheDocument();
      await user.click(screen.getByRole("button", { name: "/var/log/syslog" }));
      expect(screen.getByLabelText("Path")).toHaveValue("/var/log/syslog");
      await user.click(add());
      expect(onAdd).toHaveBeenCalledWith([{ kind: "file", server_id: A, path: "/var/log/syslog" }]);
    });

    it("adds a path that matches a pattern with a wildcard", async () => {
      const { user, onAdd } = renderDialog();
      await user.click(screen.getByRole("radio", { name: "File" }));
      await screen.findByRole("list", { name: "Patterns of Production" });
      await user.type(screen.getByLabelText("Path"), "/var/log/nginx/access.log");
      await user.click(add());
      expect(onAdd).toHaveBeenCalledWith([{ kind: "file", server_id: A, path: "/var/log/nginx/access.log" }]);
    });

    it("refuses a path that matches none of the patterns", async () => {
      const { user } = renderDialog();
      await user.click(screen.getByRole("radio", { name: "File" }));
      await screen.findByRole("list", { name: "Patterns of Production" });
      await user.type(screen.getByLabelText("Path"), "/etc/shadow");
      expect(screen.getByText("This path matches none of the group's patterns.")).toBeInTheDocument();
      expect(add()).toBeDisabled();
    });

    it("opens the group's patterns for those who manage them, and reads them again after", async () => {
      const { user } = renderDialog();
      await user.click(screen.getByRole("radio", { name: "File" }));
      await screen.findByRole("list", { name: "Patterns of Production" });
      const reads = () => vi.mocked(apiFetch).mock.calls.filter(([p]) => p === "/server-groups/g1/log-allowlist").length;
      expect(reads()).toBe(1);

      await user.click(screen.getByRole("button", { name: "Manage patterns" }));
      expect(await screen.findByRole("heading", { name: "Log file patterns of Production" })).toBeInTheDocument();
      allowlist = { ...allowlist, patterns: [...allowlist.patterns, pattern("p3", "/var/log/auth.log")] };
      await user.keyboard("{Escape}");

      await waitFor(() => expect(screen.queryByRole("heading", { name: /Log file patterns/ })).not.toBeInTheDocument());
      const list = within(await screen.findByRole("list", { name: "Patterns of Production" }));
      await waitFor(() => expect(list.getAllByRole("listitem")).toHaveLength(3));
      expect(screen.getByRole("heading", { name: "Add source" })).toBeInTheDocument();
    });

    it("shows the patterns read-only to those who do not manage them", async () => {
      allowlist = { ...allowlist, can_manage: false };
      const { user } = renderDialog();
      await user.click(screen.getByRole("radio", { name: "File" }));
      await screen.findByRole("list", { name: "Patterns of Production" });
      expect(screen.queryByRole("button", { name: "Manage patterns" })).not.toBeInTheDocument();
    });
  });

  describe("Containers", () => {
    it("lists the containers by Compose project with their state, and adds the ticked ones", async () => {
      const { user, onAdd } = renderDialog();
      await user.click(screen.getByRole("radio", { name: "Containers" }));
      const shop = within(await screen.findByRole("group", { name: "shop" }));
      expect(shop.getAllByRole("checkbox").map((c) => c.getAttribute("aria-label"))).toEqual(["db", "web"]);
      expect(shop.getByText("exited")).toBeInTheDocument();
      expect(within(screen.getByRole("group", { name: "No Compose project" })).getByText("running")).toBeInTheDocument();
      expect(apiFetch).toHaveBeenCalledWith(`/servers/${A}/containers`);

      expect(add()).toBeDisabled();
      await user.click(screen.getByRole("checkbox", { name: "web" }));
      await user.click(screen.getByRole("checkbox", { name: "cron" }));
      await user.click(add());
      expect(onAdd).toHaveBeenCalledWith([
        { kind: "container", server_id: A, container_id: "3f2a9b8c7d6e", name: "web" },
        { kind: "container", server_id: A, container_id: "1a2b3c4d5e6f", name: "cron" },
      ]);
    });

    it("does not add a container the view holds already", async () => {
      const held: LogSource = { kind: "container", server_id: A, container_id: "3f2a9b8c7d6e", name: "web" };
      const { user } = renderDialog({ current: [held] });
      await user.click(screen.getByRole("radio", { name: "Containers" }));
      const web = await screen.findByRole("checkbox", { name: "web" });
      expect(web).toBeDisabled();
      expect(web).toBeChecked();
      expect(add()).toBeDisabled();
    });
  });

  describe("Limits", () => {
    it("says them", () => {
      renderDialog();
      expect(screen.getByText("A view holds at most 16 sources, 8 per server.")).toBeInTheDocument();
    });

    it("adds nothing past 16 sources in the view", () => {
      const current = Array.from({ length: 16 }, (_, i): LogSource => ({
        kind: "file", server_id: i < 8 ? B : "s-other", path: `/var/log/f${i}`,
      }));
      renderDialog({ current });
      expect(add()).toBeDisabled();
    });

    it("adds nothing past 8 sources on the server", async () => {
      const current = Array.from({ length: 7 }, (_, i): LogSource => ({ kind: "file", server_id: A, path: `/var/log/f${i}` }));
      const { user } = renderDialog({ current });
      expect(add()).toBeEnabled();
      await user.click(screen.getByRole("radio", { name: "Containers" }));
      await user.click(await screen.findByRole("checkbox", { name: "web" }));
      expect(add()).toBeEnabled();
      await user.click(screen.getByRole("checkbox", { name: "cron" }));
      expect(add()).toBeDisabled();
    });

    it("does not add a journal the view holds already", () => {
      renderDialog({ current: [journal()] });
      expect(screen.getByText("The view holds this source already.")).toBeInTheDocument();
      expect(add()).toBeDisabled();
    });
  });
});
