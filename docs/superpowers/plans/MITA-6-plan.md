# MITA-6 implementation plan: frontend app shell (Next.js 16, shadcn sidebar and header, Cyberpunk theme)

## Goal

`frontend/` holds a Next.js 16 app whose every page sits in one shell (a collapsible sidebar with 13 items in four groups, and a header with title, search placeholder, light/dark button and account menu), themed with the Knowledge Base's Cyberpunk theme without a theme flash, built into an image that a check proves serves the shell.

## Architecture

`src/lib/navigation.ts` is the single source for the sidebar, the header title and the placeholder pages. `src/lib/theme.ts` owns the `megoo-theme` key, the setter and the pre-paint script that the root layout inlines in `<head>`. `src/app/globals.css` is the only place a colour is written: Knowledge Base tokens per `data-theme`, shadcn's and the sidebar's variables mapped onto them once, Tailwind v4 `@theme inline` on top. The `(app)` route group's layout reads shadcn's `sidebar_state` cookie and renders `AppShell` (shadcn `SidebarProvider`, `AppSidebar`, `SidebarInset` with `SiteHeader` and `<main id="main">`). A three-stage `node:22-alpine` Dockerfile builds a standalone image; the new `web` service set starts it and `npm run test:image` fetches pages from it.

## Facts this plan relies on

- Today `frontend/` holds only `.gitkeep`; there is no Node code in the repository. The root `.gitignore` holds `.venv/`, `__pycache__/`, `.pytest_cache/`, `.env` only; `create-next-app` writes `frontend/.gitignore` (keeps `node_modules`, `.next`, `next-env.d.ts` out).
- `megoocolab.toml` has the sets `test`, `migrate`, `image`; Compose files live in `tools/test-services/` and reference the build context relative to themselves (`build: ../../backend`). The runner runs `docker compose … up -d --build --wait`, so when the command starts the image is built and healthy. `megoocolab-runner` finds `megoocolab.toml` from `frontend/`.
- `AGENTS.md` → Checks → the Frontend line is `- **Frontend** (\`frontend/\`): \`npx tsc --noEmit\`, \`npx eslint <changed files>\` and \`npm test\`.` Step 12 replaces it.
- Commit subjects: `type(area): plain sentence`, body says why, every commit ends with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. Never write anything under `docs/`. Test names read as sentences.
- Commands run from `frontend/` unless a step says otherwise.
- shadcn facts used below: `SidebarProvider` writes `document.cookie = "sidebar_state=<true|false>; path=/; max-age=…"`, toggles on Ctrl/⌘+B, and `useIsMobile()` (`src/hooks/use-mobile.ts`) switches below 768 px, where `Sidebar` renders inside a `Sheet` (role `dialog`). The desktop sidebar root is `<div data-slot="sidebar" data-state="expanded|collapsed" …>`. `SidebarTrigger` has the accessible name "Toggle Sidebar". `SidebarMenuButton` takes `isActive` (→ `data-active`) and `tooltip` (shown only when collapsed and not mobile). `SidebarInset` renders a `<main>` – step 4 changes it to a `<div>` so the page has exactly one `<main>`. If a generated name differs in the installed shadcn version, use the generated one and keep the behaviour.
- PRD §15.1 page lines (used verbatim as placeholder descriptions, see L1).

## File map

| Path | Step | Responsibility |
|---|---|---|
| `frontend/.gitkeep` | 1 | deleted |
| `frontend/package.json`, `package-lock.json` | 1 | `megooitadmin-frontend` 0.1.0, exact `next` and `eslint-config-next`, scripts |
| `frontend/tsconfig.json`, `next.config.ts`, `postcss.config.mjs`, `eslint.config.mjs`, `.gitignore` | 1 | from `create-next-app`; `next.config.ts` = `output: "standalone"` only |
| `frontend/vitest.config.mts`, `vitest.setup.ts` | 1 | `npm test` (L3) |
| `frontend/src/__tests__/helpers/match-media.ts` | 1 | `mockMatchMedia()` for jsdom (L3) |
| `frontend/src/__tests__/storage.test.ts` | 1 | decision 14 guard (L4) |
| `frontend/public/.gitkeep` | 1 | keeps `public/` for the Dockerfile |
| `frontend/src/lib/navigation.ts` + `src/lib/__tests__/navigation.test.ts` | 2 | groups, items, `isActive`, `findNavItem`, `navItem` (L1) |
| `frontend/src/lib/theme.ts` + `src/lib/__tests__/theme.test.ts` | 3 | key, `storedTheme`, `systemTheme`, `setTheme`, `themeBootstrapScript` (L2) |
| `frontend/components.json`, `src/lib/utils.ts`, `src/hooks/use-mobile.ts`, `src/components/ui/*` | 4 | shadcn; caps on Button/Badge; `SidebarInset` as `div` |
| `frontend/src/components/ui/__tests__/caps.test.tsx` | 4 | Button and Badge uppercase |
| `frontend/src/app/globals.css` + `src/app/__tests__/themeTokens.test.ts` | 5 | the theme (L5) and its token/contrast test (L6) |
| `frontend/src/components/placeholder-page.tsx` + `src/components/__tests__/placeholder-page.test.tsx` | 6 | placeholder page body |
| `frontend/src/components/shell/wordmark.tsx`, `app-sidebar.tsx` + `__tests__/app-sidebar.test.tsx` | 7 | sidebar |
| `frontend/src/components/shell/theme-switch.tsx` + `__tests__/theme-switch.test.tsx` | 8 | two-state theme button |
| `frontend/src/components/shell/account-menu.tsx` + `__tests__/account-menu.test.tsx` | 9 | placeholder account menu |
| `frontend/src/components/shell/search-placeholder.tsx`, `site-header.tsx` + `__tests__/site-header.test.tsx` | 10 | header |
| `frontend/src/components/shell/app-shell.tsx` + `__tests__/app-shell.test.tsx` | 11 | the shell |
| `frontend/src/app/layout.tsx`, `icon.svg`, `(app)/layout.tsx`, `(app)/page.tsx`, `(app)/<12 routes>/page.tsx`, `(app)/[...rest]/page.tsx`, `(app)/not-found.tsx` | 12 | routes; deletes `src/app/page.tsx`, `src/app/favicon.ico` |
| `frontend/Dockerfile`, `.dockerignore`, `vitest.image.config.mts`, `image-tests/shell.test.ts` | 13 | image and its check (L7, L8) |
| `tools/test-services/docker-compose.web.yml`, `megoocolab.toml`, `AGENTS.md` | 13 | the `web` set and the Frontend check line (L8) |

---

## Code listings

### L1 `src/lib/navigation.ts`

```ts
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

/** The item a pathname belongs to, or undefined (the header then says "Page not found"). */
export function findNavItem(pathname: string): NavItem | undefined {
  return NAV_ITEMS.find((item) => isActive(pathname, item.href));
}

/** The item with exactly this route; for the page files. Throws on an unknown route. */
export function navItem(href: string): NavItem {
  const item = NAV_ITEMS.find((candidate) => candidate.href === href);
  if (!item) throw new Error(`No navigation item for ${href}`);
  return item;
}
```

### L2 `src/lib/theme.ts`

```ts
export type Theme = "light" | "dark";

export const THEME_STORAGE_KEY = "megoo-theme";

/** The stored choice, or null when nothing valid is stored or storage is blocked. */
export function storedTheme(): Theme | null {
  try {
    const value = localStorage.getItem(THEME_STORAGE_KEY);
    return value === "light" || value === "dark" ? value : null;
  } catch {
    return null;
  }
}

/** The operating system's setting; "light" without matchMedia. */
export function systemTheme(): Theme {
  return typeof window !== "undefined" && window.matchMedia?.("(prefers-color-scheme: dark)").matches
    ? "dark"
    : "light";
}

export function setTheme(theme: Theme): void {
  try {
    localStorage.setItem(THEME_STORAGE_KEY, theme);
  } catch {
    // storage blocked: the choice lasts until the page is reloaded
  }
  document.documentElement.dataset.theme = theme;
}

/** Inline <script> body run before paint so the page never flashes the wrong theme. */
export const themeBootstrapScript = `(function(){try{var p=localStorage.getItem("${THEME_STORAGE_KEY}");}catch(e){}var d=p==="dark"||(p!=="light"&&window.matchMedia&&window.matchMedia("(prefers-color-scheme: dark)").matches);document.documentElement.dataset.theme=d?"dark":"light";})();`;
```

### L3 Vitest setup

`vitest.config.mts`:

```ts
import react from "@vitejs/plugin-react";
import { fileURLToPath } from "node:url";
import { defineConfig } from "vitest/config";

export default defineConfig({
  plugins: [react()],
  resolve: { alias: { "@": fileURLToPath(new URL("./src", import.meta.url)) } },
  test: {
    environment: "jsdom",
    setupFiles: ["./vitest.setup.ts"],
    include: ["src/**/*.test.{ts,tsx}"],
    css: false,
  },
});
```

`src/__tests__/helpers/match-media.ts`:

```ts
import { vi } from "vitest";

type Listener = (event: MediaQueryListEvent) => void;

/** jsdom has no matchMedia: answer prefers-color-scheme from `dark` and max-width queries from `width`. */
export function mockMatchMedia({ dark = false, width = 1280 }: { dark?: boolean; width?: number } = {}) {
  let isDark = dark;
  const listeners = new Set<Listener>();
  Object.defineProperty(window, "innerWidth", { configurable: true, writable: true, value: width });
  window.matchMedia = vi.fn((query: string) => {
    const maxWidth = /max-width:\s*(\d+)px/.exec(query);
    const isScheme = query.includes("prefers-color-scheme: dark");
    const matches = isScheme ? isDark : maxWidth ? width <= Number(maxWidth[1]) : false;
    return {
      matches, media: query, onchange: null,
      addEventListener: (_: string, l: Listener) => { if (isScheme) listeners.add(l); },
      removeEventListener: (_: string, l: Listener) => { listeners.delete(l); },
      addListener: (l: Listener) => { if (isScheme) listeners.add(l); },
      removeListener: (l: Listener) => { listeners.delete(l); },
      dispatchEvent: () => true,
    } as unknown as MediaQueryList;
  });
  return {
    /** Change the operating system's setting and tell every listener. */
    setDark(value: boolean) {
      isDark = value;
      listeners.forEach((l) => l({ matches: value } as MediaQueryListEvent));
    },
  };
}
```

`vitest.setup.ts`:

```ts
import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { createElement, type AnchorHTMLAttributes, type MouseEvent } from "react";
import { afterEach, beforeEach, vi } from "vitest";
import { mockMatchMedia } from "./src/__tests__/helpers/match-media";

// next/link needs the app router; in jsdom it is a plain <a> that does not navigate.
vi.mock("next/link", () => ({
  default: ({ href, onClick, ...rest }: AnchorHTMLAttributes<HTMLAnchorElement> & { href: string }) =>
    createElement("a", { href, ...rest, onClick: (e: MouseEvent<HTMLAnchorElement>) => { onClick?.(e); e.preventDefault(); } }),
}));
// Tests set the route with vi.mocked(usePathname).mockReturnValue(...).
vi.mock("next/navigation", () => ({ usePathname: vi.fn(() => "/"), notFound: vi.fn() }));

beforeEach(() => {
  mockMatchMedia();
  localStorage.clear();
  delete document.documentElement.dataset.theme;
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

// jsdom has no ResizeObserver or pointer capture; Radix popups use them.
if (!("ResizeObserver" in globalThis)) {
  globalThis.ResizeObserver = class { observe() {} unobserve() {} disconnect() {} } as unknown as typeof ResizeObserver;
}
Element.prototype.hasPointerCapture ??= () => false;
Element.prototype.releasePointerCapture ??= () => {};
Element.prototype.scrollIntoView ??= () => {};
```

(`vi.restoreAllMocks` does not undo `vi.mock` module mocks; `usePathname` keeps its last `mockReturnValue`, so each test that cares sets it.)

### L4 `src/__tests__/storage.test.ts`

```ts
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, relative } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const root = fileURLToPath(new URL("../..", import.meta.url)); // frontend/
const src = join(root, "src");

function sourceFiles(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name);
    if (statSync(path).isDirectory()) return name === "__tests__" ? [] : sourceFiles(path);
    return /\.(ts|tsx)$/.test(name) ? [relative(root, path).split("\\").join("/")] : [];
  });
}

function filesMentioning(pattern: RegExp): string[] {
  return sourceFiles(src).filter((file) => pattern.test(readFileSync(join(root, file), "utf8")));
}

describe("browser storage", () => {
  it("is used only by the theme module", () => {
    expect(filesMentioning(/localStorage|sessionStorage/).filter((f) => f !== "src/lib/theme.ts")).toEqual([]);
  });

  it("gets cookies written only by shadcn's sidebar", () => {
    expect(filesMentioning(/document\.cookie/).filter((f) => f !== "src/components/ui/sidebar.tsx")).toEqual([]);
  });
});
```

### L5 `src/app/globals.css`

```css
@import "tailwindcss";
@import "tw-animate-css";

@custom-variant dark (&:where([data-theme=dark], [data-theme=dark] *));

/* The Knowledge Base's Cyberpunk theme. This file is the only place a colour is written. */
:root,
:root[data-theme="light"] {
  --bg: #f6f3ff;
  --surface: #ffffff;
  --surface-2: #ece6ff;
  --line: #d6ccf5;
  --fg: #1a0b3d;
  --muted-foreground: #6b5f99;
  --on-accent: #ffffff;
  --cyan: #0090a8;
  --pink: #d4004f;
  --green: #1f8f2c;
  --amber: #a16207;
  --violet: #6d28d9;
  /* Text tones, darkened from the Knowledge Base just enough to pass AA on every surface (themeTokens.test.ts) */
  --cyan-ink: #007286;
  --green-ink: #197725;
  --pink-ink: #cf004d;
  --amber-ink: #965b06;
  --chart-1: #0090a8;
  --chart-2: #d4004f;
  --grid: rgba(80, 40, 200, 0.06);
  --glow-cyan: none;
  --shadow: 0 1px 2px rgba(26, 11, 61, 0.08), 0 4px 16px rgba(26, 11, 61, 0.06);
  --shadow-pop: 0 4px 12px rgba(26, 11, 61, 0.1), 0 12px 32px rgba(26, 11, 61, 0.12);
  color-scheme: light;
}

:root[data-theme="dark"] {
  --bg: #0e0f13;
  --surface: #17191f;
  --surface-2: #121318;
  --line: #2a2d36;
  --fg: #eceef3;
  --muted-foreground: #8e94a3;
  --on-accent: #0e0f13;
  --cyan: #22e4ff;
  --pink: #ff3d81;
  --green: #5bff9a;
  --amber: #ffe14d;
  --violet: #c084fc;
  --cyan-ink: #22e4ff;
  --green-ink: #5bff9a;
  --pink-ink: #ff3d81;
  --amber-ink: #ffe14d;
  --chart-1: #0aa5c0;
  --chart-2: #ff3d81;
  --grid: rgba(255, 255, 255, 0.03);
  --glow-cyan: 0 0 8px rgba(34, 228, 255, 0.6);
  --shadow: 0 0 12px rgba(34, 228, 255, 0.12);
  --shadow-pop: 0 0 0 1px rgba(34, 228, 255, 0.25), 0 0 20px rgba(34, 228, 255, 0.25);
  color-scheme: dark;
}

/* shadcn's variables, mapped once through the Knowledge Base's aliases, so both themes follow */
:root {
  --background: var(--bg);
  --foreground: var(--fg);
  --card: var(--surface);
  --card-foreground: var(--fg);
  --popover: var(--surface);
  --popover-foreground: var(--fg);
  --primary: var(--cyan-ink);
  --primary-foreground: var(--on-accent);
  --secondary: var(--surface-2);
  --secondary-foreground: var(--fg);
  --muted: var(--surface-2);
  --accent: var(--surface-2);
  --accent-foreground: var(--cyan-ink);
  --destructive: var(--pink);
  --border: var(--line);
  --input: var(--line);
  --ring: var(--cyan);
  --sidebar: var(--surface);
  --sidebar-foreground: var(--fg);
  --sidebar-primary: var(--cyan-ink);
  --sidebar-primary-foreground: var(--on-accent);
  --sidebar-accent: var(--surface-2);
  --sidebar-accent-foreground: var(--cyan-ink);
  --sidebar-border: var(--line);
  --sidebar-ring: var(--cyan);
  --radius: 0.25rem;
}

@theme inline {
  --color-bg: var(--bg);
  --color-surface: var(--surface);
  --color-surface-2: var(--surface-2);
  --color-line: var(--line);
  --color-fg: var(--fg);
  --color-on-accent: var(--on-accent);
  --color-cyan: var(--cyan);
  --color-cyan-ink: var(--cyan-ink);
  --color-pink: var(--pink);
  --color-pink-ink: var(--pink-ink);
  --color-green: var(--green);
  --color-green-ink: var(--green-ink);
  --color-amber: var(--amber);
  --color-amber-ink: var(--amber-ink);
  --color-violet: var(--violet);
  --color-chart-1: var(--chart-1);
  --color-chart-2: var(--chart-2);
  --color-background: var(--background);
  --color-foreground: var(--foreground);
  --color-card: var(--card);
  --color-card-foreground: var(--card-foreground);
  --color-popover: var(--popover);
  --color-popover-foreground: var(--popover-foreground);
  --color-primary: var(--primary);
  --color-primary-foreground: var(--primary-foreground);
  --color-secondary: var(--secondary);
  --color-secondary-foreground: var(--secondary-foreground);
  --color-muted: var(--muted);
  --color-muted-foreground: var(--muted-foreground);
  --color-accent: var(--accent);
  --color-accent-foreground: var(--accent-foreground);
  --color-destructive: var(--destructive);
  --color-border: var(--border);
  --color-input: var(--input);
  --color-ring: var(--ring);
  --color-sidebar: var(--sidebar);
  --color-sidebar-foreground: var(--sidebar-foreground);
  --color-sidebar-primary: var(--sidebar-primary);
  --color-sidebar-primary-foreground: var(--sidebar-primary-foreground);
  --color-sidebar-accent: var(--sidebar-accent);
  --color-sidebar-accent-foreground: var(--sidebar-accent-foreground);
  --color-sidebar-border: var(--sidebar-border);
  --color-sidebar-ring: var(--sidebar-ring);
  --radius-sm: calc(var(--radius) - 2px);
  --radius-md: var(--radius);
  --radius-lg: var(--radius);
  --radius-xl: calc(var(--radius) + 4px);
  /* Depth follows the theme: soft shadows in light mode, cyan glows in dark mode */
  --shadow-2xs: var(--shadow);
  --shadow-xs: var(--shadow);
  --shadow-sm: var(--shadow);
  --shadow: var(--shadow);
  --shadow-md: var(--shadow-pop);
  --shadow-lg: var(--shadow-pop);
  --shadow-xl: var(--shadow-pop);
  --shadow-2xl: var(--shadow-pop);
  --font-sans: var(--font-geist), ui-sans-serif, system-ui, sans-serif;
  --font-mono: var(--font-geist-mono), ui-monospace, monospace;
  --font-brand: var(--font-orbitron), ui-sans-serif, system-ui, sans-serif;
}

@layer base {
  * {
    @apply border-border outline-ring/50;
  }
  html,
  body {
    background-color: var(--bg);
    color: var(--fg);
  }
  body {
    font-family: var(--font-sans);
    background-image:
      linear-gradient(var(--grid) 1px, transparent 1px),
      linear-gradient(90deg, var(--grid) 1px, transparent 1px);
    background-size: 22px 22px;
    background-attachment: fixed;
  }
  h1,
  h2,
  h3 {
    letter-spacing: -0.01em;
  }
}

@media (prefers-reduced-motion: reduce) {
  [data-slot="sidebar-gap"],
  [data-slot="sidebar-container"],
  [data-slot="sheet-content"],
  [data-slot="sheet-overlay"] {
    transition: none !important;
    animation: none !important;
  }
}
```

Notes: `--shadow: var(--shadow)` inside `@theme inline` names Tailwind's `shadow` utility; if Tailwind rejects the self-reference (the build or a dev page shows no shadow), rename the token to `--shadow-card` everywhere (both theme blocks, the test's expected list and this mapping) and map `--shadow: var(--shadow-card)`. If a `data-slot` name differs in the generated components, use the generated one.

### L6 `src/app/__tests__/themeTokens.test.ts`

```ts
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const css = readFileSync(fileURLToPath(new URL("../globals.css", import.meta.url)), "utf8");

function block(pattern: RegExp): string {
  const match = pattern.exec(css);
  if (!match) throw new Error(`globals.css has no block matching ${pattern}`);
  return match[1];
}
function tokens(body: string): Record<string, string> {
  return Object.fromEntries([...body.matchAll(/--([\w-]+):\s*([^;]+);/g)].map((m) => [m[1], m[2].trim()]));
}

const light = tokens(block(/:root,\s*:root\[data-theme="light"\]\s*\{([^}]*)\}/));
const dark = tokens(block(/:root\[data-theme="dark"\]\s*\{([^}]*)\}/));
const aliases = tokens(block(/(?:^|\n):root\s*\{([^}]*)\}/));

const KB_LIGHT = {
  bg: "#f6f3ff", surface: "#ffffff", "surface-2": "#ece6ff", line: "#d6ccf5", fg: "#1a0b3d",
  "muted-foreground": "#6b5f99", "on-accent": "#ffffff", cyan: "#0090a8", pink: "#d4004f", green: "#1f8f2c",
  amber: "#a16207", violet: "#6d28d9", "chart-1": "#0090a8", "chart-2": "#d4004f", grid: "rgba(80, 40, 200, 0.06)",
};
const KB_DARK = {
  bg: "#0e0f13", surface: "#17191f", "surface-2": "#121318", line: "#2a2d36", fg: "#eceef3",
  "muted-foreground": "#8e94a3", "on-accent": "#0e0f13", cyan: "#22e4ff", pink: "#ff3d81", green: "#5bff9a",
  amber: "#ffe14d", violet: "#c084fc", "chart-1": "#0aa5c0", "chart-2": "#ff3d81", grid: "rgba(255, 255, 255, 0.03)",
  "cyan-ink": "#22e4ff", "green-ink": "#5bff9a", "pink-ink": "#ff3d81", "amber-ink": "#ffe14d",
};
const ALIASES = {
  background: "var(--bg)", foreground: "var(--fg)", card: "var(--surface)", "card-foreground": "var(--fg)",
  popover: "var(--surface)", "popover-foreground": "var(--fg)", primary: "var(--cyan-ink)",
  "primary-foreground": "var(--on-accent)", secondary: "var(--surface-2)", "secondary-foreground": "var(--fg)",
  muted: "var(--surface-2)", accent: "var(--surface-2)", "accent-foreground": "var(--cyan-ink)",
  destructive: "var(--pink)", border: "var(--line)", input: "var(--line)", ring: "var(--cyan)",
  sidebar: "var(--surface)", "sidebar-foreground": "var(--fg)", "sidebar-primary": "var(--cyan-ink)",
  "sidebar-primary-foreground": "var(--on-accent)", "sidebar-accent": "var(--surface-2)",
  "sidebar-accent-foreground": "var(--cyan-ink)", "sidebar-border": "var(--line)", "sidebar-ring": "var(--cyan)",
  radius: "0.25rem",
};

function luminance(hex: string): number {
  const [r, g, b] = [1, 3, 5]
    .map((i) => parseInt(hex.slice(i, i + 2), 16) / 255)
    .map((c) => (c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4));
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}
function contrast(a: string, b: string): number {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x);
  return (hi + 0.05) / (lo + 0.05);
}

const TEXT = ["fg", "muted-foreground", "cyan-ink", "green-ink", "pink-ink", "amber-ink", "violet"];
const SURFACES = ["bg", "surface", "surface-2"];
const PAIRS = (["light", "dark"] as const).flatMap((mode) => [
  ...TEXT.flatMap((text) => SURFACES.map((surface) => [text, surface, mode] as const)),
  ["on-accent", "cyan-ink", mode] as const,
  ["on-accent", "pink", mode] as const,
]);

describe("the Cyberpunk theme tokens", () => {
  it("keep the Knowledge Base's light values", () => expect(light).toMatchObject(KB_LIGHT));
  it("keep the Knowledge Base's dark values", () => expect(dark).toMatchObject(KB_DARK));
  it("define every ink shade in light mode", () => {
    for (const ink of ["cyan-ink", "green-ink", "pink-ink", "amber-ink"]) expect(light[ink]).toMatch(/^#[0-9a-f]{6}$/);
  });
  it("map shadcn's and the sidebar's variables onto them", () => expect(aliases).toMatchObject(ALIASES));
  it("switch dark mode with data-theme, not a .dark class", () => {
    expect(css).not.toMatch(/\.dark\s*\{/);
    expect(css).toContain("@custom-variant dark (&:where([data-theme=dark], [data-theme=dark] *));");
  });
  it.each(PAIRS)("%s on %s in %s mode reaches 4.5 to 1", (text, surface, mode) => {
    const theme = mode === "light" ? light : dark;
    expect(contrast(theme[text], theme[surface])).toBeGreaterThanOrEqual(4.5);
  });
});
```

### L7 `image-tests/shell.test.ts` and `vitest.image.config.mts`

```ts
import { describe, expect, it } from "vitest";
import { NAV_ITEMS } from "../src/lib/navigation";

const BASE = process.env.FRONTEND_URL;
if (!BASE) {
  throw new Error("FRONTEND_URL is not set. Run the image check from frontend/ with: megoocolab-runner services run web -- npm run test:image");
}

async function get(path: string, init?: RequestInit) {
  const response = await fetch(new URL(path, BASE), init);
  return { status: response.status, html: await response.text() };
}
function sidebarTag(html: string): string {
  const tag = /<div[^>]*data-slot="sidebar"[^>]*>/.exec(html);
  if (!tag) throw new Error("no sidebar in the page");
  return tag[0];
}

describe("the frontend image", () => {
  it("serves the dashboard with the wordmark and a link to every page", async () => {
    const { status, html } = await get("/");
    expect(status).toBe(200);
    expect(html).toContain("MegooITAdmin");
    for (const item of NAV_ITEMS) expect(html).toContain(`href="${item.href}"`);
  });

  it("runs the theme script in the head, before the body", async () => {
    const { html } = await get("/");
    const head = html.slice(html.indexOf("<head"), html.indexOf("<body"));
    expect(head).toContain("megoo-theme");
    expect(head).toContain("dataset.theme");
  });

  it("renders the sidebar open without a cookie and collapsed when sidebar_state is false", async () => {
    expect(sidebarTag((await get("/")).html)).toContain('data-state="expanded"');
    expect(sidebarTag((await get("/", { headers: { cookie: "sidebar_state=false" } })).html)).toContain('data-state="collapsed"');
  });

  it("serves the servers page with its title", async () => {
    const { status, html } = await get("/servers");
    expect(status).toBe(200);
    expect(html).toContain("<title>Servers · MegooITAdmin</title>");
  });

  it("answers 404 for an unknown address and keeps the navigation", async () => {
    const { status, html } = await get("/no-such-page");
    expect(status).toBe(404);
    expect(html).toContain('aria-label="Main"');
    expect(html).toContain("Page not found");
  });
});
```

`vitest.image.config.mts`:

```ts
import { defineConfig } from "vitest/config";

export default defineConfig({
  test: { environment: "node", include: ["image-tests/**/*.test.ts"], testTimeout: 30_000 },
});
```

### L8 Image, Compose, service set, AGENTS.md

`frontend/Dockerfile`:

```dockerfile
FROM node:22-alpine AS deps
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci

FROM node:22-alpine AS build
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY . .
ENV NEXT_TELEMETRY_DISABLED=1
# next/font downloads Geist, Geist Mono and Orbitron here, so the build needs network access.
RUN npm run build

FROM node:22-alpine AS run
WORKDIR /app
ENV NODE_ENV=production NEXT_TELEMETRY_DISABLED=1 PORT=3000 HOSTNAME=0.0.0.0
COPY --from=build /app/public ./public
COPY --from=build /app/.next/standalone ./
COPY --from=build /app/.next/static ./.next/static
USER node
EXPOSE 3000
CMD ["node", "server.js"]
```

`frontend/.dockerignore`:

```
node_modules
.next
**/__tests__
image-tests
```

`tools/test-services/docker-compose.web.yml`:

```yaml
# The frontend image built from this checkout (the web set in megoocolab.toml).
services:
  frontend:
    build: ../../frontend
    image: ${FRONTEND_IMAGE}
    ports:
      - "127.0.0.1:${WEB_PORT}:3000"
    healthcheck:
      # The image has no curl.
      test: ["CMD", "node", "-e", "fetch('http://127.0.0.1:3000/').then((r) => process.exit(r.ok ? 0 : 1), () => process.exit(1))"]
      interval: 2s
      timeout: 5s
      retries: 60
```

Append to `megoocolab.toml`:

```toml

[services.web]
description = "The frontend image built from this checkout, for npm run test:image"
compose = ["tools/test-services/docker-compose.web.yml"]
ports = ["WEB_PORT"]

[services.web.env]
FRONTEND_IMAGE = "megooitadmin-frontend:${MEGOO_SERVICES_PROJECT}"
FRONTEND_URL = "http://localhost:${WEB_PORT}"
```

`AGENTS.md`, the Frontend line under Checks becomes:

```markdown
- **Frontend** (`frontend/`): `npx tsc --noEmit`, `npx eslint <changed files>` and `npm test`, then the image
  check: `megoocolab-runner services run web -- npm run test:image`.
```

---

## Steps

### 1. Scaffold the Next.js 16 app with Vitest and the browser-storage guard

From the repository root: `git rm frontend/.gitkeep` (create-next-app refuses a folder with unknown files), then
`npx create-next-app@16 frontend --ts --eslint --tailwind --app --src-dir --import-alias "@/*" --use-npm --disable-git --no-react-compiler --yes`.
If it writes `frontend/AGENTS.md` (and `CLAUDE.md`) about Next.js 16, keep them.

In `frontend/`:
- `package.json`: `"name": "megooitadmin-frontend"`, `"version": "0.1.0"`. Pin `next` and `eslint-config-next` to the exact installed 16.x version (remove `^`; `npm ls next` shows it; both the same). Scripts exactly: `"dev": "next dev"`, `"build": "next build"`, `"start": "next start"`, `"lint": "eslint"`, `"test": "vitest run"`, `"test:image": "vitest run --config vitest.image.config.mts"`.
- `npm install -D vitest @vitejs/plugin-react jsdom @testing-library/react @testing-library/dom @testing-library/jest-dom @testing-library/user-event`, then `npm install` so `package-lock.json` carries the new name and `0.1.0` on both top-level `version` lines.
- `next.config.ts`: only `output: "standalone"`.
- Delete the SVGs in `public/`, add `public/.gitkeep`. Replace `src/app/page.tsx` with a minimal `export default function Home() { return <main>MegooITAdmin</main>; }` (step 12 deletes it).
- Write `vitest.config.mts`, `vitest.setup.ts`, `src/__tests__/helpers/match-media.ts` (L3) — `vitest.image.config.mts` comes in step 13, so `test:image` is not run yet.

Test first: `src/__tests__/storage.test.ts` (L4). Run `npm test`: before the Vitest config exists it fails ("vitest: not found" / no config); after the config, both tests pass (no source uses storage yet).

Then: `npx tsc --noEmit`, `npx eslint .`, `npm run build` all pass.

Commit: `chore(frontend): a Next.js 16 app with Vitest replaces the empty frontend folder` (body: the shell needs a project; Vitest gives `npm test`; the storage guard enforces "no tokens in browser storage").

### 2. Navigation: four groups, 13 items, `isActive`, `findNavItem`, `navItem`

Test first `src/lib/__tests__/navigation.test.ts`:
- "lists four groups in the PRD's order": labels `["Operate","Automate","Manage","Govern"]`.
- "lists the 13 items with their routes and icons in order": compare `NAV_ITEMS.map(i => [i.title, i.href, i.icon])` against the table (import icons from `lucide-react`).
- "gives every item a unique route" and "a description".
- `isActive`: "/" active only for "/" (not "/servers"); "/servers" active for "/servers" and "/servers/12", not "/serversx" or "/".
- `findNavItem`: "/" → Dashboard, "/servers/12" → Servers, "/no-such-page" → undefined.
- `navItem("/audit")` → Audit; `navItem("/nope")` throws.

Run `npm test -- src/lib/__tests__/navigation.test.ts`: fails (module missing). Write `src/lib/navigation.ts` (L1). Run again: passes. `npx tsc --noEmit`, `npx eslint src/lib`.

Commit: `feat(frontend): the navigation lists 13 pages in four groups`.

### 3. Theme module and pre-paint script

Test first `src/lib/__tests__/theme.test.ts` (setup already gives a light OS, cleared storage, no `data-theme`; use `mockMatchMedia({ dark: true })` for a dark OS and `vi.spyOn(Storage.prototype, "getItem"/"setItem").mockImplementation(() => { throw new Error("blocked"); })` for blocked storage):
- `storedTheme`: returns "light"/"dark" when stored; null for "system", nothing stored, and throwing storage.
- `systemTheme`: "dark" with a dark OS, "light" otherwise.
- `setTheme("dark")`: `localStorage["megoo-theme"] === "dark"` and `<html data-theme="dark">`; with throwing `setItem` it still sets `data-theme`.
- the script, run as `new Function(themeBootstrapScript)()`: stored dark → dark; stored light with dark OS → light; nothing stored + dark OS → dark; nothing stored + light OS → light; throwing `getItem` + dark OS → dark.
- "names the storage key": `themeBootstrapScript` contains `"megoo-theme"`.

Run `npm test -- src/lib/__tests__/theme.test.ts`: fails. Write `src/lib/theme.ts` (L2). Passes. The storage guard still passes (theme.ts is the allowed file).

Commit: `feat(frontend): the theme is chosen before the first paint from megoo-theme or the system`.

### 4. shadcn/ui components with uppercase buttons and badges

`npx shadcn@latest init --base-color neutral --yes` (or `--defaults`); then make sure `components.json` has `"style": "new-york"`, `"rsc": true`, `"tailwind.css": "src/app/globals.css"`, `"iconLibrary": "lucide"`, aliases `components @/components`, `ui @/components/ui`, `utils @/lib/utils`, `lib @/lib`, `hooks @/hooks` (fix and re-run init if not). Then `npx shadcn@latest add sidebar button badge dropdown-menu tooltip sheet separator input skeleton --yes`. This writes `src/lib/utils.ts`, `src/hooks/use-mobile.ts`, `src/components/ui/*.tsx`, adds `lucide-react`, Radix, `class-variance-authority`, `tw-animate-css`, and rewrites `globals.css` (step 5 replaces it).

Test first `src/components/ui/__tests__/caps.test.tsx`: "buttons are uppercase, semibold and widely spaced" (`render(<Button>Save</Button>)`, `toHaveClass("uppercase","font-semibold","tracking-wider")`); "badges are uppercase". Run: fails.

Edit generated files:
- `button.tsx` cva base: replace `font-medium` with `font-semibold uppercase tracking-wider`.
- `badge.tsx` cva base: add `uppercase`.
- `sidebar.tsx` `SidebarInset`: render `<div>` instead of `<main>` (`React.ComponentProps<"div">`), so the shell has one `<main>`.
Run again: passes; storage guard passes (`sidebar.tsx` is the allowed cookie file). `npx tsc --noEmit`, `npx eslint src/components src/hooks src/lib`, `npm run build`.

Commit: `feat(frontend): shadcn's sidebar and menus, with uppercase buttons and badges`.

### 5. Cyberpunk theme tokens with darkened light-mode inks

Test first `src/app/__tests__/themeTokens.test.ts` (L6). Run `npm test -- src/app/__tests__/themeTokens.test.ts`: fails (shadcn's generated globals.css has a `.dark` block and none of the tokens).

Replace `src/app/globals.css` with L5. Run again. If a contrast case fails for a light ink, darken that hex in the smallest steps (subtract 1 from each non-zero channel, keeping the hue) until it passes, and use that value; do not change any other token. Read the passing value back into the comment-free token line.

Then `npx tsc --noEmit`, `npx eslint .`, `npm run build` (proves Tailwind accepts the `@theme inline` block; see the L5 note about the `--shadow` self-reference).

Commit: `feat(frontend): the Cyberpunk theme, with ink shades that pass WCAG AA in light mode`.

### 6. Placeholder page body

Test first `src/components/__tests__/placeholder-page.test.tsx`: `render(<PlaceholderPage href="/servers" />)` shows a level-2 heading "Servers", the description "Inventory, groups and tags, with a page per server.", and the text "Not built yet".

Write `src/components/placeholder-page.tsx` (server component, no "use client"):
`export function PlaceholderPage({ href }: { href: string })` → `const item = navItem(href)`; a `section` with `item.icon` (aria-hidden, `size-8 text-cyan-ink`), `<h2 className="text-xl font-semibold">{item.title}</h2>`, `<p className="text-muted-foreground">{item.description}</p>`, `<Badge variant="outline">Not built yet</Badge>`, inside a card (`rounded-lg border bg-card p-6 shadow-sm max-w-xl`).

Run, pass, tsc, eslint. Commit: `feat(frontend): a placeholder page names each page that is not built yet`.

### 7. Sidebar with wordmark and grouped navigation

Test first `src/components/shell/__tests__/app-sidebar.test.tsx`, rendering `<SidebarProvider><AppSidebar /></SidebarProvider>` with `vi.mocked(usePathname).mockReturnValue("/servers")`:
- "shows 13 links under four labels inside the main navigation": `within(getByRole("navigation", { name: "Main" }))` has 13 links and the texts Operate, Automate, Manage, Govern.
- "marks the current page": the Servers link has `aria-current="page"`; Dashboard has none.
- "links the wordmark to the dashboard in the brand font": `getByRole("link", { name: "MegooITAdmin" })` has `href="/"`; `getByText("MegooITAdmin")` has class `font-brand`.
Run: fails.

`src/components/shell/wordmark.tsx`: `<Link href="/" aria-label="MegooITAdmin" className="flex items-center gap-2 px-1 py-1.5">` with a mark `<span aria-hidden className="grid size-8 shrink-0 place-items-center rounded bg-cyan-ink font-brand text-sm font-bold text-on-accent shadow-(--glow-cyan)">M</span>` and `<span aria-hidden className="font-brand text-sm font-bold uppercase tracking-widest group-data-[collapsible=icon]:hidden">MegooITAdmin</span>`. (Collapsed, only the mark shows.)

`src/components/shell/app-sidebar.tsx` ("use client"): `<Sidebar collapsible="icon">`, `<SidebarHeader><Wordmark /></SidebarHeader>`, `<SidebarContent><nav aria-label="Main" className="flex flex-col">` with one `SidebarGroup` per `NAV_GROUPS` entry (groups after the first get `group-data-[collapsible=icon]:border-t group-data-[collapsible=icon]:border-sidebar-border` so labels become thin dividers), `<SidebarGroupLabel className="text-[11px] uppercase tracking-wider">`, and per item `<SidebarMenuItem><SidebarMenuButton asChild isActive={active} tooltip={item.title} className={ACTIVE}><Link href aria-current={active ? "page" : undefined} onClick={() => { if (isMobile) setOpenMobile(false); }}><item.icon aria-hidden /><span>{item.title}</span></Link></SidebarMenuButton></SidebarMenuItem>`, with `active = isActive(pathname, item.href)` and `const { isMobile, setOpenMobile } = useSidebar()`.
`ACTIVE = "relative data-[active=true]:font-semibold data-[active=true]:text-cyan-ink data-[active=true]:before:absolute data-[active=true]:before:inset-y-1 data-[active=true]:before:left-0 data-[active=true]:before:w-0.5 data-[active=true]:before:rounded-full data-[active=true]:before:bg-cyan data-[active=true]:before:shadow-(--glow-cyan)"` (tinted background comes from shadcn's `bg-sidebar-accent`).

Run, pass, tsc, eslint. Commit: `feat(frontend): the sidebar shows the wordmark and the 13 pages in four groups`.

### 8. Two-state theme switch

Test first `src/components/shell/__tests__/theme-switch.test.tsx` (`userEvent.setup()`):
- "switches from light to dark and stores the choice": start with `data-theme="light"`; click button "Switch between light and dark" → `data-theme="dark"`, `localStorage["megoo-theme"]="dark"`; click again → light.
- "still switches when storage is blocked": `setItem` throws → `data-theme` changes.
- "follows the operating system while nothing is stored": `const os = mockMatchMedia()`; render; `act(() => os.setDark(true))` → dark.
- "stops following the system after a click": click, then `os.setDark(...)` leaves `data-theme` unchanged.
- "keeps a stored choice when the system changes": stored "light", `os.setDark(true)` → still light.
Run: fails.

`src/components/shell/theme-switch.tsx` ("use client"): `const chosen = useRef(false)`. `useEffect`: `const mq = window.matchMedia?.("(prefers-color-scheme: dark)")`; if absent return; `onChange = (e: MediaQueryListEvent) => { if (!chosen.current && storedTheme() === null) document.documentElement.dataset.theme = e.matches ? "dark" : "light"; }`; add/remove `"change"` listener. Click: `chosen.current = true; setTheme(document.documentElement.dataset.theme === "dark" ? "light" : "dark")`. Render `<Button variant="ghost" size="icon" aria-label="Switch between light and dark" onClick={…}><Sun aria-hidden className="dark:hidden" /><Moon aria-hidden className="hidden dark:block" /></Button>` — both icons in the HTML, CSS picks one.

Run, pass; storage guard passes (no storage call outside theme.ts). Commit: `feat(frontend): a two-state button switches between light and dark`.

### 9. Placeholder account menu

Test first `src/components/shell/__tests__/account-menu.test.tsx`: "says sign-in is not available yet and disables both items": `render(<AccountMenu user={null} />)`; open the trigger "Account" (`await user.click(trigger)`; if Radix does not open on click in jsdom, `trigger.focus(); await user.keyboard("{Enter}")`); `findByText("Sign-in is not available yet")`; `getByRole("menuitem", { name: "Profile and security" })` and `"Sign out"` have `aria-disabled="true"`.
Run: fails.

`src/components/shell/account-menu.tsx` ("use client"): `export type AccountUser = { name: string; email: string }`; `export function AccountMenu({ user }: { user: AccountUser | null })`. `DropdownMenu` → trigger `<Button variant="ghost" size="icon" aria-label="Account"><CircleUser aria-hidden /></Button>`; content `align="end"`: `DropdownMenuLabel` shows `user.name` and `user.email` (email `text-muted-foreground text-xs`) when given, else "Sign-in is not available yet"; `DropdownMenuSeparator`; `<DropdownMenuItem disabled><UserCog />Profile and security</DropdownMenuItem>`, `<DropdownMenuItem disabled><LogOut />Sign out</DropdownMenuItem>` (MITA-8 wires them).

Run, pass, tsc, eslint. Commit: `feat(frontend): the account menu says sign-in is not available yet`.

### 10. Header with title and search placeholder

Test first `src/components/shell/__tests__/site-header.test.tsx`, rendering `<SidebarProvider><SiteHeader /></SidebarProvider>`:
- "titles the page from the route": pathname "/servers/12" → `getByRole("heading", { level: 1, name: "Servers" })`; "/" → "Dashboard".
- "says Page not found for an unknown route": "/no-such-page" → heading "Page not found".
- "shows a disabled search placeholder": every `getAllByRole("button", { name: /search/i })` is disabled.
- "holds the sidebar button, the theme button and the account menu": buttons "Toggle Sidebar", "Switch between light and dark", "Account".
Run: fails.

`src/components/shell/search-placeholder.tsx` (no hooks): `<Button variant="outline" disabled aria-label="Search, not available yet" className="hidden w-56 justify-between font-normal normal-case tracking-normal text-muted-foreground md:inline-flex"><span className="flex items-center gap-2"><Search aria-hidden />Search…</span><kbd className="rounded border px-1.5 font-mono text-[11px]">Ctrl K</kbd></Button>` and `<Button variant="ghost" size="icon" disabled aria-label="Search, not available yet" className="md:hidden"><Search aria-hidden /></Button>`. No Ctrl+K listener.

`src/components/shell/site-header.tsx` ("use client"): `title = findNavItem(usePathname())?.title ?? "Page not found"`; `<header className="sticky top-0 z-10 flex h-14 shrink-0 items-center gap-2 border-b bg-background/80 px-4 backdrop-blur">` → `<SidebarTrigger className="-ml-1" />`, `<Separator orientation="vertical" className="mx-1 h-5" />`, `<h1 className="truncate text-base font-semibold">{title}</h1>`, `<div className="ml-auto flex items-center gap-1"><SearchPlaceholder /><ThemeSwitch /><AccountMenu user={null} /></div>`.

Run, pass. Commit: `feat(frontend): the header shows the page title, search, the theme button and the account menu`.

### 11. App shell: provider, skip link, one main landmark, drawer on small screens

Test first `src/components/shell/__tests__/app-shell.test.tsx` (`beforeEach`: `document.cookie = "sidebar_state=; max-age=0; path=/"`; pathname "/"):
- "collapses and opens the sidebar from the header and remembers it in a cookie": `render(<AppShell defaultOpen>…</AppShell>)`; `[data-slot="sidebar"]` has `data-state="expanded"`; click "Toggle Sidebar" → `collapsed` and `document.cookie` contains `sidebar_state=false`; click again → `expanded`, `sidebar_state=true`.
- "starts collapsed when defaultOpen is false".
- "is a drawer on a small screen that closes when a link is followed": `mockMatchMedia({ width: 500 })`; render; click "Toggle Sidebar"; `await findByRole("dialog")`; click the "Servers" link inside it; `waitFor` no dialog.
- "has one main landmark that the skip link points at": link "Skip to content" has `href="#main"`; `document.querySelectorAll("main")` has length 1 and id "main"; children render inside it.
Run: fails.

`src/components/shell/app-shell.tsx` (no "use client"): `export function AppShell({ defaultOpen, children }: { defaultOpen: boolean; children: React.ReactNode })` → `<a href="#main" className="sr-only focus:not-sr-only focus:fixed focus:left-2 focus:top-2 focus:z-50 focus:rounded focus:bg-surface focus:px-3 focus:py-2">Skip to content</a>` then `<SidebarProvider defaultOpen={defaultOpen}><AppSidebar /><SidebarInset><SiteHeader /><main id="main" tabIndex={-1} className="flex-1 p-6 outline-none">{children}</main></SidebarInset></SidebarProvider>`. If the generated `SidebarProvider` has no `TooltipProvider`, wrap the provider in `<TooltipProvider delayDuration={0}>`.

Run, pass, `npm test` all green. Commit: `feat(frontend): every page sits in one shell with a sidebar that is a drawer on small screens`.

### 12. Root layout, routes, placeholders and the 404 page

No new unit test (next/font does not run in Vitest); the build and step 13's image check prove it.

- `src/app/layout.tsx` (rewrite): `Geist({ variable: "--font-geist", subsets: ["latin"] })`, `Geist_Mono({ variable: "--font-geist-mono", subsets: ["latin"] })`, `Orbitron({ variable: "--font-orbitron", subsets: ["latin"], weight: ["700"] })`; `metadata: Metadata = { title: { default: "MegooITAdmin", template: "%s · MegooITAdmin" }, description: "Self-hosted IT administration with AI agents" }`; `viewport: Viewport = { themeColor: [{ media: "(prefers-color-scheme: light)", color: "#f6f3ff" }, { media: "(prefers-color-scheme: dark)", color: "#0e0f13" }] }`; `<html lang="en" suppressHydrationWarning className={`${geist.variable} ${geistMono.variable} ${orbitron.variable} antialiased`}><head><script dangerouslySetInnerHTML={{ __html: themeBootstrapScript }} /></head><body className="min-h-svh">{children}</body></html>`.
- `src/app/icon.svg`: `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32"><rect width="32" height="32" rx="4" fill="#0e0f13"/><path d="M8 23V9l8 9 8-9v14" fill="none" stroke="#22e4ff" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"/></svg>`. Delete `src/app/favicon.ico` and `src/app/page.tsx`.
- `src/app/(app)/layout.tsx`: `export default async function AppLayout({ children }: { children: React.ReactNode }) { const defaultOpen = (await cookies()).get("sidebar_state")?.value !== "false"; return <AppShell defaultOpen={defaultOpen}>{children}</AppShell>; }` (`cookies` from `next/headers`).
- `src/app/(app)/page.tsx` and one `page.tsx` per route folder `servers sessions logs assistant playbooks approvals knowledge-base secrets scheduler reports audit settings`, each:
  ```tsx
  import type { Metadata } from "next";
  import { PlaceholderPage } from "@/components/placeholder-page";
  import { navItem } from "@/lib/navigation";

  export const metadata: Metadata = { title: navItem("/servers").title };

  export default function ServersPage() {
    return <PlaceholderPage href="/servers" />;
  }
  ```
- `src/app/(app)/[...rest]/page.tsx`: `import { notFound } from "next/navigation"; export default function UnknownPage() { notFound(); }`.
- `src/app/(app)/not-found.tsx`: `metadata = { title: "Page not found" }` is not allowed in not-found files in every version — instead render `<title>Page not found · MegooITAdmin</title>` only if the build warns; body: `<section className="max-w-xl space-y-4"><h2 className="text-xl font-semibold">Page not found</h2><p className="text-muted-foreground">There is no page at this address.</p><Button asChild><Link href="/">Back to the dashboard</Link></Button></section>`.

Run `npx tsc --noEmit`, `npx eslint .`, `npm test`, `npm run build` (the route list shows the 13 routes and `[...rest]`). Manually `npm run start` and `curl -s -o /dev/null -w '%{http_code}' localhost:3000/no-such-page` → 404 (no `loading.tsx` may exist; `notFound()` runs before anything streams).

Commit: `feat(frontend): the 13 pages and a 404 page render inside the shell without a theme flash`.

### 13. Frontend image and its check through the web service set

Write `vitest.image.config.mts` and `image-tests/shell.test.ts` (L7). Run `npm run test:image` without the set: fails with the message naming `megoocolab-runner services run web -- npm run test:image`.

Write `frontend/Dockerfile`, `frontend/.dockerignore`, `tools/test-services/docker-compose.web.yml`, append the `web` set to `megoocolab.toml`, and update the Frontend line in `AGENTS.md` (all L8).

Run from `frontend/`: `megoocolab-runner services run web -- npm run test:image` (builds the image first; a few minutes): all five tests pass. Also `npx tsc --noEmit` (image-tests are type-checked), `npx eslint .`, `npm test`.

Commit: `test(frontend): a check proves the built frontend image serves the shell` (body: the image is what ships; the `web` set builds and starts it so the check runs against real HTML).

---

## Final verification

From `frontend/`:

```
npx tsc --noEmit
npx eslint .
npm test
npm run build
megoocolab-runner services run web -- npm run test:image
```

`git show HEAD:frontend/package.json | grep version` and the two top-level `version` lines of `package-lock.json` are `0.1.0`. The finish report says the backend, security (`make test-security`) and release (`make release-check`) checks were skipped: the backend is unchanged and the other two are not in the repository yet.
