import {
  BookOpen, Bot, CalendarClock, FileText, KeyRound, LayoutDashboard, ListChecks, Logs,
  ScrollText, Server, Settings, ShieldCheck, SquareTerminal, type LucideIcon,
} from "lucide-react";

export type NavItem = { title: string; href: string; icon: LucideIcon; description: string };
export type NavGroup = { label: string; items: NavItem[] };

export const NAV_GROUPS: NavGroup[] = [
  { label: "Operate", items: [
    { title: "Dashboard", href: "/", icon: LayoutDashboard, description: "Live fleet overview and firing alerts." },
    { title: "Servers", href: "/servers", icon: Server, description: "Inventory, groups and tags, with a page per server." },
    { title: "Sessions", href: "/sessions", icon: SquareTerminal, description: "Workspace of open SSH terminals and RDP desktops as tabs." },
    { title: "Logs", href: "/logs", icon: Logs, description: "Live log viewer across servers and containers, with saved views." },
  ] },
  { label: "Automate", items: [
    { title: "Assistant", href: "/assistant", icon: Bot, description: "Agent chat, with inline approval cards." },
    { title: "Playbooks", href: "/playbooks", icon: ListChecks, description: "Playbook library, editor, runs and their history." },
    { title: "Approvals", href: "/approvals", icon: ShieldCheck, description: "Shared approvals inbox." },
  ] },
  { label: "Manage", items: [
    { title: "Knowledge base", href: "/knowledge-base", icon: BookOpen, description: "Entries, search and review queue." },
    { title: "Secrets", href: "/secrets", icon: KeyRound, description: "Write-only secret management and usage log." },
    { title: "Scheduler", href: "/scheduler", icon: CalendarClock, description: "Scheduled jobs and run history." },
    { title: "Reports", href: "/reports", icon: FileText, description: "Stored reports, templates and Generate." },
  ] },
  { label: "Govern", items: [
    { title: "Audit", href: "/audit", icon: ScrollText, description: "Timeline of human and AI activity, approvals, sessions and recordings, with exports." },
    { title: "Settings", href: "/settings", icon: Settings, description: "Users, roles, agent profiles and platform settings." },
  ] },
];

export const NAV_ITEMS: NavItem[] = NAV_GROUPS.flatMap((group) => group.items);

/** "/" matches only "/"; any other item matches its route and everything below it. */
export function isActive(pathname: string, href: string): boolean {
  if (href === "/") return pathname === "/";
  return pathname === href || pathname.startsWith(`${href}/`);
}

/** The item a pathname belongs to, or undefined. */
export function findNavItem(pathname: string): NavItem | undefined {
  return NAV_ITEMS.find((item) => isActive(pathname, item.href));
}

/** Pages outside the sidebar, by their exact route. */
const PAGE_TITLES: Record<string, string> = { "/profile": "Profile and security" };

/** The header's title for a pathname: its nav item's title, a page outside the nav, or "Page not found". */
export function pageTitle(pathname: string): string {
  return findNavItem(pathname)?.title ?? PAGE_TITLES[pathname] ?? "Page not found";
}

/** The item with exactly this route; for the page files. Throws on an unknown route. */
export function navItem(href: string): NavItem {
  const item = NAV_ITEMS.find((candidate) => candidate.href === href);
  if (!item) throw new Error(`No navigation item for ${href}`);
  return item;
}
