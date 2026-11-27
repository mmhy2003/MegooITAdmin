import { act, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { NotificationsPage } from "@/components/settings/notifications-page";
import type { Channel, EmailSettings } from "@/lib/alerts";
import { ApiError, apiFetch } from "@/lib/api";

vi.mock("@/lib/api", async (orig) => ({ ...(await orig<typeof import("@/lib/api")>()), apiFetch: vi.fn() }));
vi.mock("@/lib/auth/navigate");

const NOT_SET_UP: EmailSettings = {
  enabled: false,
  host: null,
  port: 587,
  security: "starttls",
  username: null,
  password_set: false,
  from_name: "MegooITAdmin",
  from_address: null,
  extra_addresses: [],
  min_severity: "warning",
  last_delivery: null,
};
const SET_UP: EmailSettings = {
  ...NOT_SET_UP,
  enabled: true,
  host: "smtp.example.com",
  port: 465,
  security: "tls",
  username: "alerts",
  password_set: true,
  from_address: "alerts@example.com",
  extra_addresses: ["oncall@example.com", "noc@example.com"],
  min_severity: "critical",
  last_delivery: { state: "failed", at: "2026-11-27T10:00:00Z", error: "auth_failed" },
};

const SLACK: Channel = {
  id: "c1",
  name: "Ops chat",
  kind: "webhook_slack",
  min_severity: "critical",
  enabled: true,
  hint: "hooks.slack.com",
  created_at: "2026-11-27T09:00:00Z",
  updated_at: "2026-11-27T09:00:00Z",
  last_delivery: { state: "delivered", at: new Date().toISOString(), error: null },
};
const JSON_HOOK: Channel = {
  ...SLACK,
  id: "c2",
  name: "Ticketing",
  kind: "webhook_json",
  min_severity: "warning",
  enabled: false,
  hint: "tickets.example.com",
  last_delivery: { state: "pending", at: "2026-11-27T10:00:00Z", error: "timeout" },
};
const TELEGRAM: Channel = {
  ...SLACK,
  id: "c3",
  name: "On call",
  kind: "telegram",
  hint: "chat -1001234",
  last_delivery: { state: "failed", at: "2026-11-27T10:00:00Z", error: "http_status" },
};

beforeEach(() => {
  vi.mocked(apiFetch).mockReset();
});

type Init = { method?: string; body?: unknown };

function mockApi(
  email: EmailSettings,
  test: () => Promise<unknown> = async () => ({ ok: true, error: null }),
  channels: Channel[] = [],
  channelCall: (path: string, init: Init) => Promise<unknown> = async () => undefined,
) {
  vi.mocked(apiFetch).mockImplementation(async (path: string, init?: Init) => {
    if (path === "/notifications/email/test" && init?.method === "POST") return test();
    if (path === "/notifications/email" && !init) return email;
    if (path === "/notification-channels" && !init) return channels;
    if (path.startsWith("/notification-channels/") && init) return channelCall(path, init);
    throw new Error(`unexpected ${path}`);
  });
}

async function channelsCard() {
  return within(
    (await screen.findByRole("heading", { name: "Webhooks and chat" })).closest("[data-slot=card]") as HTMLElement,
  );
}

function rowOf(name: string) {
  return within(screen.getByText(name).closest("li") as HTMLElement);
}

async function emailCard() {
  return within((await screen.findByRole("heading", { name: "Email" })).closest("[data-slot=card]") as HTMLElement);
}

describe("NotificationsPage", () => {
  it("says email is not set up and offers to set it up", async () => {
    mockApi(NOT_SET_UP);
    render(<NotificationsPage />);
    const user = userEvent.setup();

    const card = await emailCard();
    expect(card.getByText("Email is not set up. Alerts are shown in the app only.")).toBeInTheDocument();
    expect(card.queryByRole("button", { name: "Send a test" })).not.toBeInTheDocument();
    await user.click(card.getByRole("button", { name: "Set up email" }));

    expect(within(screen.getByRole("dialog")).getByRole("heading", { name: "Email" })).toBeInTheDocument();
  });

  it("shows the server, the sender, who gets it, the filter and the last delivery once set up", async () => {
    mockApi(SET_UP);
    render(<NotificationsPage />);

    const card = await emailCard();
    expect(await card.findByText("smtp.example.com:465")).toBeInTheDocument();
    expect(card.getByText("MegooITAdmin <alerts@example.com>")).toBeInTheDocument();
    expect(
      card.getByText("The Owner and the Admins of the server's group, plus 2 more addresses"),
    ).toBeInTheDocument();
    expect(card.getByText("Critical only")).toBeInTheDocument();
    expect(card.getByText(/Failed after 6 tries/)).toHaveTextContent(
      "Failed after 6 tries: The mail server refused the user name or the password.",
    );
    expect(card.getByRole("button", { name: "Edit" })).toBeInTheDocument();
    expect(card.getByRole("button", { name: "Send a test" })).toBeInTheDocument();
    expect(card.queryByText(/not set up/)).not.toBeInTheDocument();
  });

  it("says who gets it without extra addresses, with both severities and no message yet", async () => {
    mockApi({ ...SET_UP, extra_addresses: [], min_severity: "warning", last_delivery: null });
    render(<NotificationsPage />);

    const card = await emailCard();
    expect(await card.findByText("The Owner and the Admins of the server's group")).toBeInTheDocument();
    expect(card.getByText("Warning and Critical")).toBeInTheDocument();
    expect(card.getByText("No message sent yet.")).toBeInTheDocument();
  });

  it("opens the dialog from Edit with the saved settings", async () => {
    mockApi(SET_UP);
    render(<NotificationsPage />);
    const user = userEvent.setup();

    await user.click(await (await emailCard()).findByRole("button", { name: "Edit" }));

    expect(within(screen.getByRole("dialog")).getByRole("textbox", { name: "Host" })).toHaveValue("smtp.example.com");
  });

  it("sends a test and says it went to the Owner's address", async () => {
    mockApi(SET_UP);
    render(<NotificationsPage />);
    const user = userEvent.setup();

    await user.click(await (await emailCard()).findByRole("button", { name: "Send a test" }));

    expect(apiFetch).toHaveBeenCalledWith("/notifications/email/test", { method: "POST" });
    expect(await screen.findByText("Test sent to your address.")).toBeInTheDocument();
  });

  it("says why a test was not delivered", async () => {
    mockApi(SET_UP, async () => ({ ok: false, error: "connection_failed" }));
    render(<NotificationsPage />);
    const user = userEvent.setup();

    await user.click(await (await emailCard()).findByRole("button", { name: "Send a test" }));

    expect(await screen.findByText("The connection failed.")).toBeInTheDocument();
  });

  it("shows a refused test", async () => {
    mockApi(SET_UP, async () => {
      throw new ApiError(409, "email_not_set_up");
    });
    render(<NotificationsPage />);
    const user = userEvent.setup();

    await user.click(await (await emailCard()).findByRole("button", { name: "Send a test" }));

    expect(await screen.findByText("Set up email first.")).toBeInTheDocument();
  });

  it("says there are no webhooks or chats yet, and offers to add one", async () => {
    mockApi(NOT_SET_UP);
    render(<NotificationsPage />);
    const user = userEvent.setup();

    const card = await channelsCard();
    expect(await card.findByText("No webhooks or chats yet.")).toBeInTheDocument();
    await user.click(card.getByRole("button", { name: "Add a channel" }));

    expect(within(screen.getByRole("dialog")).getByRole("heading", { name: "Add a channel" })).toBeInTheDocument();
  });

  it("lists each channel with its kind, hint, filter, switch and last delivery", async () => {
    mockApi(NOT_SET_UP, undefined, [SLACK, JSON_HOOK, TELEGRAM]);
    render(<NotificationsPage />);

    await screen.findByText("Ops chat");
    const slack = rowOf("Ops chat");
    expect(slack.getByText("Slack-compatible · hooks.slack.com")).toBeInTheDocument();
    expect(slack.getByText("Critical only")).toBeInTheDocument();
    expect(slack.getByRole("switch", { name: "Enabled" })).toBeChecked();
    expect(slack.getByText("Delivered just now.")).toBeInTheDocument();
    for (const name of ["Send a test", "Edit Ops chat", "Delete Ops chat"]) {
      expect(slack.getByRole("button", { name })).toBeInTheDocument();
    }

    const json = rowOf("Ticketing");
    expect(json.getByText("Generic JSON · tickets.example.com")).toBeInTheDocument();
    expect(json.getByText("Warning and Critical")).toBeInTheDocument();
    expect(json.getByRole("switch", { name: "Enabled" })).not.toBeChecked();
    expect(json.getByText(/Retrying/)).toHaveTextContent("Retrying: The other side did not answer in time.");

    const telegram = rowOf("On call");
    expect(telegram.getByText("Telegram · chat -1001234")).toBeInTheDocument();
    const failed = telegram.getByText(/Failed after 6 tries/);
    expect(failed).toHaveTextContent("Failed after 6 tries: The address answered with an error.");
    expect(failed).toHaveClass("text-pink-ink");
    expect(screen.queryByText("No webhooks or chats yet.")).not.toBeInTheDocument();
  });

  it("switches a channel off and reloads the list", async () => {
    const channelCall = vi.fn(async () => ({ ...SLACK, enabled: false }));
    mockApi(NOT_SET_UP, undefined, [SLACK], channelCall);
    render(<NotificationsPage />);
    const user = userEvent.setup();

    await screen.findByText("Ops chat");
    await user.click(rowOf("Ops chat").getByRole("switch", { name: "Enabled" }));

    expect(channelCall).toHaveBeenCalledWith("/notification-channels/c1", { method: "PATCH", body: { enabled: false } });
    await vi.waitFor(() =>
      expect(vi.mocked(apiFetch).mock.calls.filter(([path]) => path === "/notification-channels")).toHaveLength(2),
    );
  });

  it("shows a refused switch", async () => {
    mockApi(NOT_SET_UP, undefined, [SLACK], async () => {
      throw new ApiError(404, "not_found");
    });
    render(<NotificationsPage />);
    const user = userEvent.setup();

    await screen.findByText("Ops chat");
    await user.click(rowOf("Ops chat").getByRole("switch", { name: "Enabled" }));

    expect(await screen.findByText("It does not exist, or you cannot see it.")).toBeInTheDocument();
  });

  it("sends a test to a channel and says how it went, next to it", async () => {
    const channelCall = vi.fn(async (path: string) =>
      path === "/notification-channels/c1/test" ? { ok: true, error: null } : { ok: false, error: "http_status" },
    );
    mockApi(NOT_SET_UP, undefined, [SLACK, TELEGRAM], channelCall);
    render(<NotificationsPage />);
    const user = userEvent.setup();

    await screen.findByText("Ops chat");
    await user.click(rowOf("Ops chat").getByRole("button", { name: "Send a test" }));
    expect(channelCall).toHaveBeenCalledWith("/notification-channels/c1/test", { method: "POST" });
    expect(await rowOf("Ops chat").findByText("Test delivered.")).toBeInTheDocument();

    await user.click(rowOf("On call").getByRole("button", { name: "Send a test" }));
    const refused = await rowOf("On call").findByText("The address answered with an error.");
    expect(refused).toHaveClass("text-pink-ink");
    expect(rowOf("Ops chat").getByText("Test delivered.")).toBeInTheDocument();
  });

  it("opens the dialog from Edit with the saved channel", async () => {
    mockApi(NOT_SET_UP, undefined, [SLACK]);
    render(<NotificationsPage />);
    const user = userEvent.setup();

    await user.click(await screen.findByRole("button", { name: "Edit Ops chat" }));

    const dialog = within(screen.getByRole("dialog"));
    expect(dialog.getByRole("heading", { name: "Edit Ops chat" })).toBeInTheDocument();
    expect(dialog.getByRole("textbox", { name: "Name" })).toHaveValue("Ops chat");
  });

  it("names the channel before deleting it, then reloads the list", async () => {
    const channelCall = vi.fn(async () => undefined);
    mockApi(NOT_SET_UP, undefined, [SLACK], channelCall);
    render(<NotificationsPage />);
    const user = userEvent.setup();

    await user.click(await screen.findByRole("button", { name: "Delete Ops chat" }));
    const dialog = within(screen.getByRole("dialog"));
    expect(dialog.getByRole("heading", { name: "Delete Ops chat?" })).toBeInTheDocument();
    await user.click(dialog.getByRole("button", { name: "Delete channel" }));

    expect(channelCall).toHaveBeenCalledWith("/notification-channels/c1", { method: "DELETE" });
    await vi.waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(vi.mocked(apiFetch).mock.calls.filter(([path]) => path === "/notification-channels")).toHaveLength(2);
  });

  it("shows a refused deletion in the confirmation", async () => {
    mockApi(NOT_SET_UP, undefined, [SLACK], async () => {
      throw new ApiError(500, "error");
    });
    render(<NotificationsPage />);
    const user = userEvent.setup();

    await user.click(await screen.findByRole("button", { name: "Delete Ops chat" }));
    const dialog = within(screen.getByRole("dialog"));
    await user.click(dialog.getByRole("button", { name: "Delete channel" }));

    expect(await dialog.findByText("Something went wrong. Try again.")).toBeInTheDocument();
  });

  it("keeps a failed channel load shown when the email loads after it", async () => {
    let loadEmail: (email: EmailSettings) => void = () => {};
    vi.mocked(apiFetch).mockImplementation(async (path: string) => {
      if (path === "/notifications/email") return new Promise((resolve) => (loadEmail = resolve));
      throw new ApiError(403, "forbidden");
    });
    render(<NotificationsPage />);

    expect(await screen.findByText("You do not have the rights to do this.")).toBeInTheDocument();
    act(() => loadEmail(SET_UP));

    expect(await screen.findByText("smtp.example.com:465")).toBeInTheDocument();
    expect(screen.getByText("You do not have the rights to do this.")).toBeInTheDocument();
  });

  it("shows a failed load", async () => {
    vi.mocked(apiFetch).mockRejectedValue(new ApiError(403, "forbidden"));
    render(<NotificationsPage />);

    expect(await screen.findByText("You do not have the rights to do this.")).toBeInTheDocument();
  });
});
