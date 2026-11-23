import { render, screen, within } from "@testing-library/react";
import { usePathname } from "next/navigation";
import { describe, expect, it, vi } from "vitest";
import { SettingsTabs } from "@/components/settings/settings-tabs";

describe("SettingsTabs", () => {
  it("links to Users and Server groups and marks the current page", () => {
    vi.mocked(usePathname).mockReturnValue("/settings/groups");
    render(<SettingsTabs />);

    const nav = within(screen.getByRole("navigation", { name: "Settings" }));
    expect(nav.getByRole("link", { name: "Users" })).toHaveAttribute("href", "/settings/users");
    expect(nav.getByRole("link", { name: "Users" })).not.toHaveAttribute("aria-current");
    expect(nav.getByRole("link", { name: "Server groups" })).toHaveAttribute("href", "/settings/groups");
    expect(nav.getByRole("link", { name: "Server groups" })).toHaveAttribute("aria-current", "page");
  });

  it("marks Users on the Users page", () => {
    vi.mocked(usePathname).mockReturnValue("/settings/users");
    render(<SettingsTabs />);

    expect(screen.getByRole("link", { name: "Users" })).toHaveAttribute("aria-current", "page");
    expect(screen.getByRole("link", { name: "Server groups" })).not.toHaveAttribute("aria-current");
  });
});
