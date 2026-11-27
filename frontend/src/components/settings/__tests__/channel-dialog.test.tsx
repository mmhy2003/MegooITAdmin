import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ChannelDialog } from "@/components/settings/channel-dialog";
import type { Channel } from "@/lib/alerts";
import { ApiError, apiFetch } from "@/lib/api";

vi.mock("@/lib/api", async (orig) => ({ ...(await orig<typeof import("@/lib/api")>()), apiFetch: vi.fn() }));
vi.mock("@/lib/auth/navigate");

const SLACK: Channel = {
  id: "c1",
  name: "Ops chat",
  kind: "webhook_slack",
  min_severity: "critical",
  enabled: true,
  hint: "hooks.slack.com",
  created_at: "2026-11-27T09:00:00Z",
  updated_at: "2026-11-27T09:00:00Z",
  last_delivery: null,
};
const TELEGRAM: Channel = { ...SLACK, id: "c2", name: "On call", kind: "telegram", hint: "chat -1001234" };
const TOKEN = "123456:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdef";
const SLACK_HINT =
  "The Slack format also works with Mattermost, Rocket.Chat, Google Chat and Discord (add /slack to its address).";

beforeEach(() => {
  vi.mocked(apiFetch).mockReset();
  vi.mocked(apiFetch).mockResolvedValue(SLACK);
});

function renderDialog(channel: Channel | null) {
  const onSaved = vi.fn();
  render(<ChannelDialog channel={channel} open onOpenChange={vi.fn()} onSaved={onSaved} />);
  return { onSaved, user: userEvent.setup() };
}

async function choose(user: ReturnType<typeof userEvent.setup>, select: string, option: string) {
  await user.click(screen.getByRole("combobox", { name: select }));
  await user.click(await screen.findByRole("option", { name: option }));
}

describe("ChannelDialog", () => {
  it("starts a new webhook with its address and the Slack hint", () => {
    renderDialog(null);

    expect(screen.getByRole("heading", { name: "Add a channel" })).toBeInTheDocument();
    expect(screen.getByRole("textbox", { name: "Name" })).toHaveValue("");
    expect(screen.getByRole("combobox", { name: "Kind" })).toHaveTextContent("Generic JSON");
    const url = screen.getByRole("textbox", { name: "URL" });
    expect(url).toHaveValue("");
    expect(url).toBeRequired();
    expect(url).toHaveAccessibleDescription(SLACK_HINT);
    expect(screen.queryByLabelText("Bot token")).not.toBeInTheDocument();
    expect(screen.getByRole("radio", { name: "Warning and Critical" })).toBeChecked();
    expect(screen.getByRole("switch", { name: "Enabled" })).toBeChecked();
  });

  it("creates a Slack-compatible webhook", async () => {
    const { onSaved, user } = renderDialog(null);

    await user.type(screen.getByRole("textbox", { name: "Name" }), "  Ops chat ");
    await choose(user, "Kind", "Slack-compatible");
    await user.type(screen.getByRole("textbox", { name: "URL" }), "https://hooks.slack.com/services/T/B/x");
    await user.click(screen.getByRole("radio", { name: "Critical only" }));
    await user.click(screen.getByRole("switch", { name: "Enabled" }));
    await user.click(screen.getByRole("button", { name: "Save" }));

    expect(apiFetch).toHaveBeenCalledWith("/notification-channels", {
      method: "POST",
      body: {
        name: "Ops chat",
        kind: "webhook_slack",
        min_severity: "critical",
        enabled: false,
        url: "https://hooks.slack.com/services/T/B/x",
      },
    });
    expect(onSaved).toHaveBeenCalled();
  });

  it("asks a Telegram chat for its bot token and chat ID instead of an address", async () => {
    const { onSaved, user } = renderDialog(null);

    await user.type(screen.getByRole("textbox", { name: "Name" }), "On call");
    await choose(user, "Kind", "Telegram");
    expect(screen.queryByRole("textbox", { name: "URL" })).not.toBeInTheDocument();
    const token = screen.getByLabelText("Bot token");
    expect(token).toHaveAttribute("type", "password");
    expect(token).toBeRequired();
    expect(screen.getByRole("textbox", { name: "Chat ID" })).toBeRequired();
    await user.type(token, TOKEN);
    await user.type(screen.getByRole("textbox", { name: "Chat ID" }), "-1001234");
    await user.click(screen.getByRole("button", { name: "Save" }));

    expect(apiFetch).toHaveBeenCalledWith("/notification-channels", {
      method: "POST",
      body: { name: "On call", kind: "telegram", min_severity: "warning", enabled: true, bot_token: TOKEN, chat_id: "-1001234" },
    });
    expect(onSaved).toHaveBeenCalled();
  });

  it("shows a saved webhook without its address", () => {
    renderDialog(SLACK);

    expect(screen.getByRole("heading", { name: "Edit Ops chat" })).toBeInTheDocument();
    expect(screen.getByRole("textbox", { name: "Name" })).toHaveValue("Ops chat");
    expect(screen.getByRole("combobox", { name: "Kind" })).toHaveTextContent("Slack-compatible");
    const url = screen.getByRole("textbox", { name: "URL" });
    expect(url).toHaveValue("");
    expect(url).not.toBeRequired();
    expect(url).toHaveAttribute("placeholder", "Saved, type to replace");
    expect(url).toHaveAccessibleDescription(`Saved: hooks.slack.com. ${SLACK_HINT}`);
    expect(screen.getByRole("radio", { name: "Critical only" })).toBeChecked();
    expect(screen.getByRole("button", { name: "Save" })).toBeDisabled();
  });

  it("sends only the changed fields, and the address only when typed", async () => {
    const { onSaved, user } = renderDialog(SLACK);

    const name = screen.getByRole("textbox", { name: "Name" });
    await user.clear(name);
    await user.type(name, "Ops");
    await user.click(screen.getByRole("button", { name: "Save" }));

    expect(apiFetch).toHaveBeenLastCalledWith("/notification-channels/c1", { method: "PATCH", body: { name: "Ops" } });
    expect(onSaved).toHaveBeenCalledTimes(1);

    await user.type(screen.getByRole("textbox", { name: "URL" }), "https://chat.example.com/hooks/1");
    await user.click(screen.getByRole("button", { name: "Save" }));

    expect(apiFetch).toHaveBeenLastCalledWith("/notification-channels/c1", {
      method: "PATCH",
      body: { name: "Ops", url: "https://chat.example.com/hooks/1" },
    });
  });

  it("keeps a webhook's saved address when only its format changes", async () => {
    const { user } = renderDialog(SLACK);

    await choose(user, "Kind", "Generic JSON");
    expect(screen.getByRole("textbox", { name: "URL" })).toHaveAttribute("placeholder", "Saved, type to replace");
    await user.click(screen.getByRole("button", { name: "Save" }));

    expect(apiFetch).toHaveBeenCalledWith("/notification-channels/c1", {
      method: "PATCH",
      body: { kind: "webhook_json" },
    });
  });

  it("shows a saved Telegram chat without its token and chat ID, and sends the part typed", async () => {
    const { user } = renderDialog(TELEGRAM);

    const token = screen.getByLabelText("Bot token");
    const chat = screen.getByRole("textbox", { name: "Chat ID" });
    for (const field of [token, chat]) {
      expect(field).toHaveValue("");
      expect(field).not.toBeRequired();
      expect(field).toHaveAttribute("placeholder", "Saved, type to replace");
    }
    expect(screen.getByText("Saved: chat -1001234.")).toBeInTheDocument();
    await user.type(chat, "@oncall_team");
    await user.click(screen.getByRole("button", { name: "Save" }));

    expect(apiFetch).toHaveBeenCalledWith("/notification-channels/c2", {
      method: "PATCH",
      body: { chat_id: "@oncall_team" },
    });
  });

  it("asks for the new secret when a webhook becomes a Telegram chat", async () => {
    const { user } = renderDialog(SLACK);

    await choose(user, "Kind", "Telegram");
    const token = screen.getByLabelText("Bot token");
    expect(token).toBeRequired();
    expect(token).not.toHaveAttribute("placeholder");
    expect(screen.queryByText(/Saved:/)).not.toBeInTheDocument();
    await user.type(token, TOKEN);
    await user.type(screen.getByRole("textbox", { name: "Chat ID" }), "42");
    await user.click(screen.getByRole("button", { name: "Save" }));

    expect(apiFetch).toHaveBeenCalledWith("/notification-channels/c1", {
      method: "PATCH",
      body: { kind: "telegram", bot_token: TOKEN, chat_id: "42" },
    });
  });

  it("shows a refusal and stays open", async () => {
    vi.mocked(apiFetch).mockRejectedValue(new ApiError(422, "webhook_url_https"));
    const { onSaved, user } = renderDialog(null);

    await user.type(screen.getByRole("textbox", { name: "Name" }), "Ops");
    await user.type(screen.getByRole("textbox", { name: "URL" }), "http://chat.example.com/hook");
    await user.click(screen.getByRole("button", { name: "Save" }));

    expect(await screen.findByText("The address must start with https://.")).toBeInTheDocument();
    expect(onSaved).not.toHaveBeenCalled();
  });
});
