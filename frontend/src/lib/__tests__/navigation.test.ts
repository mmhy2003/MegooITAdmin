import {
  BookOpen, Bot, CalendarClock, FileText, KeyRound, LayoutDashboard, ListChecks, Logs,
  ScrollText, Server, Settings, ShieldCheck, SquareTerminal,
} from "lucide-react";
import { describe, expect, it } from "vitest";
import { findNavItem, isActive, NAV_GROUPS, NAV_ITEMS, navItem } from "@/lib/navigation";

describe("navigation", () => {
  it("lists four groups in the PRD's order", () => {
    expect(NAV_GROUPS.map((group) => group.label)).toEqual(["Operate", "Automate", "Manage", "Govern"]);
  });

  it("lists the 13 items with their routes and icons in order", () => {
    const expected = [
      ["Dashboard", "/", LayoutDashboard],
      ["Servers", "/servers", Server],
      ["Sessions", "/sessions", SquareTerminal],
      ["Logs", "/logs", Logs],
      ["Assistant", "/assistant", Bot],
      ["Playbooks", "/playbooks", ListChecks],
      ["Approvals", "/approvals", ShieldCheck],
      ["Knowledge base", "/knowledge-base", BookOpen],
      ["Secrets", "/secrets", KeyRound],
      ["Scheduler", "/scheduler", CalendarClock],
      ["Reports", "/reports", FileText],
      ["Audit", "/audit", ScrollText],
      ["Settings", "/settings", Settings],
    ];
    expect(NAV_ITEMS.map((item) => [item.title, item.href, item.icon])).toEqual(expected);
    expect(NAV_GROUPS.map((group) => group.items)).toEqual([
      NAV_ITEMS.slice(0, 4),
      NAV_ITEMS.slice(4, 7),
      NAV_ITEMS.slice(7, 11),
      NAV_ITEMS.slice(11),
    ]);
  });

  it("gives every item a unique route and a description", () => {
    expect(new Set(NAV_ITEMS.map((item) => item.href)).size).toBe(NAV_ITEMS.length);
    for (const item of NAV_ITEMS) expect(item.description.trim()).not.toBe("");
  });
});

describe("isActive", () => {
  it("treats the dashboard as active only on the root", () => {
    expect(isActive("/", "/")).toBe(true);
    expect(isActive("/servers", "/")).toBe(false);
  });

  it("treats an item as active on its route and the pages below it", () => {
    expect(isActive("/servers", "/servers")).toBe(true);
    expect(isActive("/servers/12", "/servers")).toBe(true);
    expect(isActive("/serversx", "/servers")).toBe(false);
    expect(isActive("/", "/servers")).toBe(false);
  });
});

describe("findNavItem", () => {
  it("finds the item a pathname belongs to", () => {
    expect(findNavItem("/")?.title).toBe("Dashboard");
    expect(findNavItem("/servers/12")?.title).toBe("Servers");
  });

  it("finds nothing for an unknown pathname", () => {
    expect(findNavItem("/no-such-page")).toBeUndefined();
  });
});

describe("navItem", () => {
  it("returns the item with exactly this route", () => {
    expect(navItem("/audit").title).toBe("Audit");
  });

  it("throws on an unknown route", () => {
    expect(() => navItem("/nope")).toThrow("No navigation item for /nope");
  });
});
