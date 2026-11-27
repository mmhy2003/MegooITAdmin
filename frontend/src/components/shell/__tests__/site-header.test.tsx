import { cleanup, render, screen, within } from "@testing-library/react";
import { usePathname } from "next/navigation";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { SiteHeader } from "@/components/shell/site-header";
import { SidebarProvider } from "@/components/ui/sidebar";
import { apiFetch } from "@/lib/api";

vi.mock("@/lib/api", async (orig) => ({ ...(await orig<typeof import("@/lib/api")>()), apiFetch: vi.fn() }));
vi.mock("@/hooks/use-refresh", () => ({ useRefresh: vi.fn() }));

beforeEach(() => {
  vi.mocked(apiFetch).mockResolvedValue({ unseen: 0, firing: 0, events: [] });
});

function renderHeader(pathname: string) {
  vi.mocked(usePathname).mockReturnValue(pathname);
  render(
    <SidebarProvider>
      <SiteHeader user={{ name: "Olive Owner", email: "owner@example.com" }} />
    </SidebarProvider>,
  );
}

const title = () => screen.getByRole("heading", { level: 1 });

describe("SiteHeader", () => {
  it("titles the page from the route", () => {
    renderHeader("/servers/12");
    expect(screen.getByRole("heading", { level: 1, name: "Servers" })).toBeInTheDocument();
    cleanup();
    renderHeader("/");
    expect(screen.getByRole("heading", { level: 1, name: "Dashboard" })).toBeInTheDocument();
  });

  it("titles the profile page", () => {
    renderHeader("/profile");
    expect(title()).toHaveAccessibleName("Profile and security");
  });

  it("says Page not found for an unknown route", () => {
    renderHeader("/no-such-page");
    expect(title()).toHaveAccessibleName("Page not found");
  });

  it("shows a disabled search placeholder", () => {
    renderHeader("/");
    const buttons = screen.getAllByRole("button", { name: /search/i });
    expect(buttons.length).toBeGreaterThan(0);
    for (const button of buttons) expect(button).toBeDisabled();
  });

  it("holds the sidebar button, the alerts bell, the theme button and the account menu", async () => {
    renderHeader("/");
    await screen.findByRole("button", { name: "Alerts, 0 new" });
    for (const name of ["Toggle Sidebar", "Switch between light and dark", "Account"]) {
      expect(screen.getByRole("button", { name })).toBeInTheDocument();
    }
  });

  it("puts the bell before the theme button", async () => {
    renderHeader("/");
    const names = within(screen.getByRole("banner"))
      .getAllByRole("button")
      .map((b) => b.getAttribute("aria-label"));
    expect(names.indexOf("Alerts, 0 new")).toBeGreaterThan(-1);
    expect(names.indexOf("Alerts, 0 new")).toBe(names.indexOf("Switch between light and dark") - 1);
    await screen.findByRole("button", { name: "Alerts, 0 new" });
  });
});
