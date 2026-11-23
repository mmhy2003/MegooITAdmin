import { render, screen, within } from "@testing-library/react";
import { usePathname } from "next/navigation";
import { describe, expect, it, vi } from "vitest";
import { AppSidebar } from "@/components/shell/app-sidebar";
import { SidebarProvider } from "@/components/ui/sidebar";

function renderSidebar() {
  vi.mocked(usePathname).mockReturnValue("/servers");
  render(
    <SidebarProvider>
      <AppSidebar />
    </SidebarProvider>,
  );
}

describe("AppSidebar", () => {
  it("shows 13 links under four labels inside the main navigation", () => {
    renderSidebar();
    const nav = within(screen.getByRole("navigation", { name: "Main" }));
    expect(nav.getAllByRole("link")).toHaveLength(13);
    for (const label of ["Operate", "Automate", "Manage", "Govern"]) {
      expect(nav.getByText(label)).toBeInTheDocument();
    }
  });

  it("marks the current page", () => {
    renderSidebar();
    expect(screen.getByRole("link", { name: "Servers" })).toHaveAttribute("aria-current", "page");
    expect(screen.getByRole("link", { name: "Dashboard" })).not.toHaveAttribute("aria-current");
  });

  it("links the wordmark to the dashboard in the brand font", () => {
    renderSidebar();
    expect(screen.getByRole("link", { name: "MegooITAdmin" })).toHaveAttribute("href", "/");
    expect(screen.getByText("MegooITAdmin")).toHaveClass("font-brand");
  });
});
