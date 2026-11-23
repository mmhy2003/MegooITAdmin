import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { usePathname } from "next/navigation";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { mockMatchMedia } from "@/__tests__/helpers/match-media";
import { AppShell } from "@/components/shell/app-shell";

const sidebar = () => document.querySelector('[data-slot="sidebar"]');
const toggle = () => screen.getByRole("button", { name: "Toggle Sidebar" });

describe("AppShell", () => {
  beforeEach(() => {
    document.cookie = "sidebar_state=; max-age=0; path=/";
    vi.mocked(usePathname).mockReturnValue("/");
  });

  it("collapses and opens the sidebar from the header and remembers it in a cookie", async () => {
    const user = userEvent.setup();
    render(<AppShell defaultOpen><p>content</p></AppShell>);
    expect(sidebar()).toHaveAttribute("data-state", "expanded");

    await user.click(toggle());
    expect(sidebar()).toHaveAttribute("data-state", "collapsed");
    expect(document.cookie).toContain("sidebar_state=false");

    await user.click(toggle());
    expect(sidebar()).toHaveAttribute("data-state", "expanded");
    expect(document.cookie).toContain("sidebar_state=true");
  });

  it("starts collapsed when defaultOpen is false", () => {
    render(<AppShell defaultOpen={false}><p>content</p></AppShell>);
    expect(sidebar()).toHaveAttribute("data-state", "collapsed");
  });

  it("is a drawer on a small screen that closes when a link is followed", async () => {
    mockMatchMedia({ width: 500 });
    const user = userEvent.setup();
    render(<AppShell defaultOpen><p>content</p></AppShell>);

    await user.click(toggle());
    const dialog = await screen.findByRole("dialog");
    await user.click(within(dialog).getByRole("link", { name: "Servers" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  });

  it("has one main landmark that the skip link points at", () => {
    render(<AppShell defaultOpen><p>content</p></AppShell>);
    expect(screen.getByRole("link", { name: "Skip to content" })).toHaveAttribute("href", "#main");
    const mains = document.querySelectorAll("main");
    expect(mains).toHaveLength(1);
    expect(mains[0]).toHaveAttribute("id", "main");
    expect(mains[0]).toHaveTextContent("content");
  });
});
