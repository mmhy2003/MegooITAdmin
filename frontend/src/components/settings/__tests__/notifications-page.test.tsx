import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { NotificationsPage } from "@/components/settings/notifications-page";
import type { EmailSettings } from "@/lib/alerts";
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

beforeEach(() => {
  vi.mocked(apiFetch).mockReset();
});

function mockApi(email: EmailSettings, test: () => Promise<unknown> = async () => ({ ok: true, error: null })) {
  vi.mocked(apiFetch).mockImplementation(async (path: string, init?: { method?: string }) => {
    if (path === "/notifications/email/test" && init?.method === "POST") return test();
    if (path === "/notifications/email" && !init) return email;
    throw new Error(`unexpected ${path}`);
  });
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

  it("reserves the webhooks and chat card", async () => {
    mockApi(NOT_SET_UP);
    render(<NotificationsPage />);

    expect(await screen.findByRole("heading", { name: "Webhooks and chat" })).toBeInTheDocument();
  });

  it("shows a failed load", async () => {
    vi.mocked(apiFetch).mockRejectedValue(new ApiError(403, "forbidden"));
    render(<NotificationsPage />);

    expect(await screen.findByText("You do not have the rights to do this.")).toBeInTheDocument();
  });
});
