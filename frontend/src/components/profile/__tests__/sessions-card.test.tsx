import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { formatTime } from "@/components/profile/profile-page";
import { SessionsCard, type SessionRow } from "@/components/profile/sessions-card";
import { ApiError, apiFetch } from "@/lib/api";

vi.mock("@/lib/api", async (orig) => ({ ...(await orig<typeof import("@/lib/api")>()), apiFetch: vi.fn() }));
vi.mock("@/lib/auth/navigate");

const CURRENT: SessionRow = {
  id: "s1",
  current: true,
  created_at: "2026-11-20T09:30:00Z",
  last_seen_at: "2026-11-23T08:00:00Z",
  ip: "10.0.0.1",
  user_agent: "Firefox on Linux",
  mfa_method: "totp",
};

const OTHER: SessionRow = {
  id: "s2",
  current: false,
  created_at: "2026-11-21T10:00:00Z",
  last_seen_at: "2026-11-22T11:00:00Z",
  ip: "10.0.0.2",
  user_agent: "Safari on iPhone",
  mfa_method: "totp",
};

beforeEach(() => {
  vi.mocked(apiFetch).mockReset();
});

function mockApi(remove: () => Promise<unknown> = async () => undefined) {
  let rows = [CURRENT, OTHER];
  vi.mocked(apiFetch).mockImplementation(async (path: string, init?: { method?: string }) => {
    if (path === "/auth/sessions") return rows;
    if (path === `/auth/sessions/${OTHER.id}` && init?.method === "DELETE") {
      const answer = await remove();
      rows = [CURRENT];
      return answer;
    }
    throw new Error(`unexpected ${path}`);
  });
}

function deleteCalls() {
  return vi.mocked(apiFetch).mock.calls.filter(([, init]) => (init as { method?: string } | undefined)?.method === "DELETE");
}

async function openSignOut() {
  render(<SessionsCard />);
  const user = userEvent.setup();
  await user.click(await screen.findByRole("button", { name: "Sign out the session on Safari on iPhone" }));
  return user;
}

describe("SessionsCard", () => {
  it("lists the sessions and marks the current one, which has no Sign out button", async () => {
    mockApi();
    render(<SessionsCard />);

    expect(await screen.findByText("Safari on iPhone")).toBeInTheDocument();
    expect(screen.getByText("Sessions")).toBeInTheDocument();
    expect(screen.getByText("Browsers signed in to your account.")).toBeInTheDocument();
    const current = screen.getByText("Firefox on Linux").closest("tr")!;
    expect(within(current).getByText("This session")).toBeInTheDocument();
    expect(within(current).queryByRole("button")).not.toBeInTheDocument();
    expect(within(current).getByText("10.0.0.1")).toBeInTheDocument();
    expect(within(current).getByText(formatTime(CURRENT.created_at))).toBeInTheDocument();
    expect(within(current).getByText(formatTime(CURRENT.last_seen_at))).toBeInTheDocument();
    const other = screen.getByText("Safari on iPhone").closest("tr")!;
    expect(within(other).queryByText("This session")).not.toBeInTheDocument();
    expect(within(other).getByRole("button", { name: "Sign out the session on Safari on iPhone" })).toBeInTheDocument();
    expect(apiFetch).toHaveBeenCalledWith("/auth/sessions");
  });

  it("signs out another session after confirming, and reloads the list", async () => {
    mockApi();
    const user = await openSignOut();

    const dialog = screen.getByRole("dialog", { name: "Sign out this session?" });
    expect(within(dialog).getByText("That browser has to sign in again.")).toBeInTheDocument();
    await user.click(within(dialog).getByRole("button", { name: "Sign out" }));

    expect(apiFetch).toHaveBeenCalledWith(`/auth/sessions/${OTHER.id}`, { method: "DELETE" });
    await waitFor(() => expect(screen.queryByText("Safari on iPhone")).not.toBeInTheDocument());
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(screen.getByText("Firefox on Linux")).toBeInTheDocument();
  });

  it("sends nothing on Cancel", async () => {
    mockApi();
    const user = await openSignOut();

    await user.click(screen.getByRole("button", { name: "Cancel" }));

    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(deleteCalls()).toHaveLength(0);
    expect(screen.getByText("Safari on iPhone")).toBeInTheDocument();
  });

  it("shows a refusal inside the dialog", async () => {
    mockApi(async () => {
      throw new ApiError(0, "unreachable");
    });
    const user = await openSignOut();

    await user.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Sign out" }));

    expect(await within(screen.getByRole("dialog")).findByRole("alert")).toHaveTextContent(
      "The server is not answering. Try again in a moment.",
    );
  });

  it("shows 'Unknown device' and a dash when the browser and address are not known", async () => {
    vi.mocked(apiFetch).mockResolvedValue([{ ...OTHER, user_agent: null, ip: null }]);
    render(<SessionsCard />);

    expect(await screen.findByText("Unknown device")).toBeInTheDocument();
    expect(screen.getByText("—")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Sign out the session on Unknown device" })).toBeInTheDocument();
  });

  it("says when the sessions cannot be loaded", async () => {
    vi.mocked(apiFetch).mockRejectedValue(new ApiError(0, "unreachable"));
    render(<SessionsCard />);

    expect(await screen.findByRole("alert")).toHaveTextContent("The server is not answering. Try again in a moment.");
  });
});
