import { cleanup, render, screen } from "@testing-library/react";
import { usePathname } from "next/navigation";
import { describe, expect, it, vi } from "vitest";
import { SiteHeader } from "@/components/shell/site-header";
import { SidebarProvider } from "@/components/ui/sidebar";

function renderHeader(pathname: string) {
  vi.mocked(usePathname).mockReturnValue(pathname);
  render(
    <SidebarProvider>
      <SiteHeader />
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

  it("holds the sidebar button, the theme button and the account menu", () => {
    renderHeader("/");
    for (const name of ["Toggle Sidebar", "Switch between light and dark", "Account"]) {
      expect(screen.getByRole("button", { name })).toBeInTheDocument();
    }
  });
});
