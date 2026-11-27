import { render, screen } from "@testing-library/react";
import { usePathname } from "next/navigation";
import { beforeEach, describe, expect, it, vi } from "vitest";
import SettingsLayout from "@/app/(app)/settings/layout";
import type { SessionUser } from "@/lib/auth/gate";
import { requireUser } from "@/lib/auth/server";

vi.mock("@/lib/auth/server", () => ({ requireUser: vi.fn() }));

const OWNER: SessionUser = { id: "u1", name: "Olive Owner", email: "owner@example.com", platform_role: "owner" };
const ADMIN: SessionUser = { id: "u2", name: "Ada Admin", email: "ada@example.com", platform_role: null };

async function renderLayout(user: SessionUser) {
  vi.mocked(requireUser).mockResolvedValue(user);
  render(await SettingsLayout({ children: <p>the users page</p> }));
}

describe("Settings layout", () => {
  beforeEach(() => {
    vi.mocked(usePathname).mockReturnValue("/settings/users");
  });

  it("shows an Owner the tabs and the page", async () => {
    await renderLayout(OWNER);

    expect(screen.getByRole("navigation", { name: "Settings" })).toBeInTheDocument();
    expect(screen.getByText("the users page")).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Settings are for the Owner" })).not.toBeInTheDocument();
  });

  it.each([ADMIN, { ...ADMIN, platform_role: "auditor" } as SessionUser])(
    "shows anyone else a notice pointing to Profile and security, without the page",
    async (user) => {
      await renderLayout(user);

      expect(screen.getByRole("heading", { name: "Settings are for the Owner" })).toBeInTheDocument();
      expect(
        screen.getByText(
          "Only the Owner of this installation manages people, server groups, alert rules and notifications. Your own access is on Profile and security.",
        ),
      ).toBeInTheDocument();
      expect(screen.getByRole("link", { name: "Profile and security" })).toHaveAttribute("href", "/profile");
      expect(screen.queryByRole("navigation", { name: "Settings" })).not.toBeInTheDocument();
      expect(screen.queryByText("the users page")).not.toBeInTheDocument();
    },
  );
});
