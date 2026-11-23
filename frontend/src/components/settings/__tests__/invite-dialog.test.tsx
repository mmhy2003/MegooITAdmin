import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { formatTime } from "@/components/profile/profile-page";
import { InviteDialog } from "@/components/settings/invite-dialog";
import { InviteLinkDialog } from "@/components/settings/invite-link-dialog";
import { ApiError, apiFetch } from "@/lib/api";
import type { InviteLink, ServerGroup } from "@/lib/access";

vi.mock("@/lib/api", async (orig) => ({ ...(await orig<typeof import("@/lib/api")>()), apiFetch: vi.fn() }));
vi.mock("@/lib/auth/navigate");

const GROUPS: ServerGroup[] = [
  { id: "g-staging", name: "staging", description: null, created_at: "2026-11-01T00:00:00Z", member_count: 0 },
];

const LINK: InviteLink = { user_id: "u9", token: "tok-123", expires_at: "2026-12-01T10:00:00Z" };

beforeEach(() => {
  vi.mocked(apiFetch).mockReset();
});

async function fillIn() {
  const user = userEvent.setup();
  await user.type(screen.getByLabelText("Name"), "Ada Lovelace");
  await user.type(screen.getByLabelText("Email"), "ada@example.com");
  await user.click(screen.getByRole("combobox", { name: "Role in staging" }));
  await user.click(await screen.findByRole("option", { name: "Operator" }));
  return user;
}

describe("InviteDialog", () => {
  it("posts the name, the email and the access, then hands the link over", async () => {
    vi.mocked(apiFetch).mockResolvedValue(LINK);
    const onCreated = vi.fn();
    render(<InviteDialog groups={GROUPS} open onOpenChange={vi.fn()} onCreated={onCreated} />);
    expect(screen.getByRole("heading", { name: "Invite a person" })).toBeInTheDocument();

    const user = await fillIn();
    await user.click(screen.getByRole("button", { name: "Create invite link" }));

    expect(apiFetch).toHaveBeenCalledWith("/users", {
      method: "POST",
      body: {
        name: "Ada Lovelace",
        email: "ada@example.com",
        platform_role: null,
        grants: [
          {
            group_id: "g-staging",
            role: "operator",
            connect_ssh: true,
            connect_rdp: true,
            view_logs: true,
            view_processes: true,
            manage_processes: false,
            run_playbooks: true,
            manage_playbooks: false,
          },
        ],
      },
    });
    expect(onCreated).toHaveBeenCalledWith(LINK, "Ada Lovelace");
  });

  it("says when the email is taken", async () => {
    vi.mocked(apiFetch).mockRejectedValue(new ApiError(409, "email_taken"));
    const onCreated = vi.fn();
    render(<InviteDialog groups={GROUPS} open onOpenChange={vi.fn()} onCreated={onCreated} />);

    const user = await fillIn();
    await user.click(screen.getByRole("button", { name: "Create invite link" }));

    expect(await screen.findByText("An account with this email exists already.")).toBeInTheDocument();
    expect(onCreated).not.toHaveBeenCalled();
  });
});

describe("InviteLinkDialog", () => {
  it("shows the link once, with when it stops working, and copies it", async () => {
    const onDone = vi.fn();
    render(<InviteLinkDialog link={LINK} name="Ada Lovelace" onDone={onDone} />);
    const user = userEvent.setup();

    expect(screen.getByRole("heading", { name: "Invite link for Ada Lovelace" })).toBeInTheDocument();
    const field = screen.getByRole("textbox", { name: "Invite link" });
    expect(field).toHaveValue(`${window.location.origin}/invite#tok-123`);
    expect(field).toHaveAttribute("readonly");
    expect(
      screen.getByText(`This link is shown once. It works until ${formatTime(LINK.expires_at)}.`),
    ).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Copy link" }));
    expect(await navigator.clipboard.readText()).toBe(`${window.location.origin}/invite#tok-123`);
    expect(screen.getByRole("button", { name: "Copied" })).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Done" }));
    expect(onDone).toHaveBeenCalled();
  });

  it("is closed without a link", () => {
    render(<InviteLinkDialog link={null} name="" onDone={vi.fn()} />);
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });
});
