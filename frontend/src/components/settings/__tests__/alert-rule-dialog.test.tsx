import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { AlertRuleDialog } from "@/components/settings/alert-rule-dialog";
import type { ServerGroup } from "@/lib/access";
import type { AlertRule } from "@/lib/alerts";
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
    server_count: 1,
    can_manage: true,
  };
}

const GROUPS = [group("g-production", "production"), group("g-staging", "staging")];
const SERVERS = [{ id: "s-web", name: "web-01" } as Server, { id: "s-db", name: "db-01" } as Server];

const DISK: AlertRule = {
  id: "r-disk",
  name: "Disk almost full",
  metric: "disk.used_percent",
  comparison: "above",
  threshold: 90,
  duration_seconds: 600,
  severity: "critical",
  server_group_id: "g-staging",
  server_group_name: "staging",
  server_id: null,
  server_name: null,
  enabled: true,
  revision: 1,
  suggested_playbook_id: null,
  firing_count: 0,
  created_at: "2026-11-01T00:00:00Z",
  updated_at: "2026-11-01T00:00:00Z",
};

/** The lists answer their paths; a save answers `saved`, or throws `error`. */
function answer({ saved, error }: { saved?: unknown; error?: ApiError } = {}) {
  vi.mocked(apiFetch).mockImplementation(async (path: string, init?: { method?: string }) => {
    if (init?.method === undefined && path === "/server-groups") return GROUPS;
    if (init?.method === undefined && path === "/servers") return SERVERS;
    if (error) throw error;
    return saved;
  });
}

beforeEach(() => {
  vi.mocked(apiFetch).mockReset();
  answer({ saved: DISK });
});

function renderDialog(props: Partial<Parameters<typeof AlertRuleDialog>[0]> = {}) {
  const onSaved = vi.fn();
  render(<AlertRuleDialog open onOpenChange={vi.fn()} onSaved={onSaved} {...props} />);
  return { onSaved, user: userEvent.setup() };
}

async function choose(user: ReturnType<typeof userEvent.setup>, select: string, option: string) {
  await user.click(screen.getByRole("combobox", { name: select }));
  await user.click(await screen.findByRole("option", { name: option }));
}

async function retype(user: ReturnType<typeof userEvent.setup>, label: string, text: string) {
  await user.clear(screen.getByLabelText(label));
  await user.type(screen.getByLabelText(label), text);
}

describe("AlertRuleDialog", () => {
  it("creates a rule with every field", async () => {
    const { user, onSaved } = renderDialog();

    expect(screen.getByRole("heading", { name: "New alert rule" })).toBeInTheDocument();
    expect(screen.getByRole("textbox", { name: "Name" })).toHaveAccessibleDescription("1 to 80 characters.");
    expect(screen.getByRole("textbox", { name: "Name" })).toHaveAttribute("maxLength", "80");
    await user.type(screen.getByRole("textbox", { name: "Name" }), "Memory short");
    await choose(user, "Watch", "Memory used");
    await retype(user, "Limit", "85");
    await retype(user, "For", "15");
    await user.click(screen.getByRole("radio", { name: "Critical" }));
    await user.click(screen.getByRole("radio", { name: "A server group" }));
    await choose(user, "Server group", "production");
    await user.click(screen.getByRole("button", { name: "Create rule" }));

    expect(apiFetch).toHaveBeenCalledWith("/alert-rules", {
      method: "POST",
      body: {
        name: "Memory short",
        metric: "mem.used_percent",
        comparison: "above",
        threshold: 85,
        duration_seconds: 900,
        severity: "critical",
        server_group_id: "g-production",
        server_id: null,
        enabled: true,
      },
    });
    expect(onSaved).toHaveBeenCalled();
  });

  it("creates a rule for one server, below its limit", async () => {
    const { user } = renderDialog();

    await user.type(screen.getByRole("textbox", { name: "Name" }), "Inodes low");
    await choose(user, "Watch", "Inodes used");
    await user.click(screen.getByRole("radio", { name: "Below" }));
    await user.click(screen.getByRole("radio", { name: "A server" }));
    expect(screen.queryByRole("combobox", { name: "Server group" })).toBeNull();
    await choose(user, "Server", "db-01");
    await user.click(screen.getByRole("button", { name: "Create rule" }));

    expect(apiFetch).toHaveBeenCalledWith("/alert-rules", {
      method: "POST",
      body: {
        name: "Inodes low",
        metric: "disk.inodes_used_percent",
        comparison: "below",
        threshold: 90,
        duration_seconds: 600,
        severity: "warning",
        server_group_id: null,
        server_id: "s-db",
        enabled: true,
      },
    });
  });

  it("waits for a server group or a server to be chosen", async () => {
    const { user } = renderDialog();

    await user.type(screen.getByRole("textbox", { name: "Name" }), "Disk");
    await user.click(screen.getByRole("radio", { name: "A server" }));
    expect(screen.getByRole("button", { name: "Create rule" })).toBeDisabled();
    await choose(user, "Server", "web-01");
    expect(screen.getByRole("button", { name: "Create rule" })).toBeEnabled();
  });

  it("hides the comparison and the limit for Unreachable, and sends neither", async () => {
    const { user } = renderDialog();

    await user.type(screen.getByRole("textbox", { name: "Name" }), "Down");
    await choose(user, "Watch", "Unreachable");
    expect(screen.queryByRole("radiogroup", { name: "Comparison" })).toBeNull();
    expect(screen.queryByLabelText("Limit")).toBeNull();
    await retype(user, "For", "5");
    expect(screen.getByText("Unreachable for 5 min")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Create rule" }));

    expect(apiFetch).toHaveBeenCalledWith(
      "/alert-rules",
      expect.objectContaining({
        body: expect.objectContaining({
          metric: "unreachable",
          comparison: null,
          threshold: null,
          duration_seconds: 300,
        }),
      }),
    );
  });

  it("shows the limit's unit and maximum per metric", async () => {
    const { user } = renderDialog();

    expect(screen.getByLabelText("Limit")).toHaveAttribute("max", "100");
    expect(screen.getByText("%")).toBeInTheDocument();
    await choose(user, "Watch", "Load per core (5 min)");
    expect(screen.getByLabelText("Limit")).toHaveAttribute("max", "1000");
    expect(screen.getByText("per core")).toBeInTheDocument();
    expect(screen.queryByText("%")).toBeNull();
  });

  it("takes 0 to 1440 minutes, and says what 0 does", () => {
    renderDialog();
    const minutes = screen.getByLabelText("For");

    expect(minutes).toHaveValue(10);
    expect(minutes).toHaveAttribute("min", "0");
    expect(minutes).toHaveAttribute("max", "1440");
    expect(minutes).toHaveAccessibleDescription("0 fires at the first sample");
  });

  it("says the rule in a sentence as it is typed", async () => {
    const { user } = renderDialog();

    expect(screen.getByText("Space used above 90% for 10 min")).toBeInTheDocument();
    await user.click(screen.getByRole("radio", { name: "Below" }));
    await retype(user, "Limit", "10");
    expect(screen.getByText("Space used below 10% for 10 min")).toBeInTheDocument();
    await retype(user, "For", "0");
    expect(screen.getByText("Space used below 10%")).toBeInTheDocument();
    await choose(user, "Watch", "Load per core (15 min)");
    await retype(user, "Limit", "1.5");
    expect(screen.getByText("Load per core (15 min) below 1.5 per core")).toBeInTheDocument();
  });

  it("edits a rule, and saves only its changed fields once something differs", async () => {
    const { user, onSaved } = renderDialog({ rule: DISK });

    expect(screen.getByRole("heading", { name: "Edit Disk almost full" })).toBeInTheDocument();
    expect(screen.getByRole("textbox", { name: "Name" })).toHaveValue("Disk almost full");
    expect(screen.getByRole("combobox", { name: "Watch" })).toHaveTextContent("Space used");
    expect(screen.getByRole("radio", { name: "Above" })).toBeChecked();
    expect(screen.getByLabelText("Limit")).toHaveValue(90);
    expect(screen.getByLabelText("For")).toHaveValue(10);
    expect(screen.getByRole("radio", { name: "Critical" })).toBeChecked();
    expect(screen.getByRole("radio", { name: "A server group" })).toBeChecked();
    expect(await screen.findByRole("combobox", { name: "Server group" })).toHaveTextContent("staging");
    const save = screen.getByRole("button", { name: "Save" });
    expect(save).toBeDisabled();

    await retype(user, "Limit", "95");
    expect(save).toBeEnabled();
    await retype(user, "Limit", "90");
    expect(save).toBeDisabled();

    await retype(user, "Limit", "95");
    await retype(user, "For", "20");
    await user.click(save);

    expect(apiFetch).toHaveBeenCalledWith("/alert-rules/r-disk", {
      method: "PATCH",
      body: { threshold: 95, duration_seconds: 1200 },
    });
    expect(onSaved).toHaveBeenCalled();
  });

  it("sends both scope fields when the scope changes", async () => {
    const { user } = renderDialog({ rule: DISK });

    await user.click(screen.getByRole("radio", { name: "A server" }));
    await choose(user, "Server", "web-01");
    await user.click(screen.getByRole("button", { name: "Save" }));

    expect(apiFetch).toHaveBeenCalledWith("/alert-rules/r-disk", {
      method: "PATCH",
      body: { server_group_id: null, server_id: "s-web" },
    });
  });

  it("clears the comparison and the limit of a rule that turns to Unreachable", async () => {
    const { user } = renderDialog({ rule: DISK });

    await choose(user, "Watch", "Unreachable");
    await user.click(screen.getByRole("button", { name: "Save" }));

    expect(apiFetch).toHaveBeenCalledWith("/alert-rules/r-disk", {
      method: "PATCH",
      body: { metric: "unreachable", comparison: null, threshold: null },
    });
  });

  it("says when another rule has the name", async () => {
    answer({ error: new ApiError(409, "rule_name_taken") });
    const { user, onSaved } = renderDialog();

    await user.type(screen.getByRole("textbox", { name: "Name" }), "Disk");
    await user.click(screen.getByRole("button", { name: "Create rule" }));

    expect(await screen.findByText("An alert rule with this name exists already.")).toBeInTheDocument();
    expect(onSaved).not.toHaveBeenCalled();
  });

  it("says when the limit does not fit", async () => {
    answer({ error: new ApiError(422, "bad_threshold") });
    const { user } = renderDialog({ rule: DISK });

    await retype(user, "Limit", "99");
    await user.click(screen.getByRole("button", { name: "Save" }));

    expect(await screen.findByText("The limit does not fit this measure.")).toBeInTheDocument();
  });

  it("reloads the lists when the chosen group is gone", async () => {
    answer({ error: new ApiError(422, "unknown_group") });
    const { user } = renderDialog();

    await user.type(screen.getByRole("textbox", { name: "Name" }), "Disk");
    await user.click(screen.getByRole("radio", { name: "A server group" }));
    await choose(user, "Server group", "staging");
    await user.click(screen.getByRole("button", { name: "Create rule" }));

    expect(
      await screen.findByText("A server group was deleted meanwhile. The list has been reloaded."),
    ).toBeInTheDocument();
    expect(vi.mocked(apiFetch).mock.calls.filter(([path]) => path === "/server-groups")).toHaveLength(2);
  });

  it("is closed when not open", () => {
    renderDialog({ open: false });
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(apiFetch).not.toHaveBeenCalled();
  });
});
