# MITA-6 design: frontend app shell (Next.js 16, shadcn sidebar and header, Cyberpunk theme)

## Goal

After this task, `frontend/` holds a Next.js 16 app whose every page sits in one shell: a collapsible sidebar with the 13 navigation items in four groups, and a header with the page title, a search placeholder, a light/dark button and an account menu. The shell uses the Knowledge Base's Cyberpunk theme in both modes and never flashes the wrong one. A `Dockerfile` builds the image, and a check proves that the built image serves the shell. Mockup v3 shows the result.

## What the repository looks like today

- `frontend/` holds only `.gitkeep`. There is no Node code anywhere in the repository.
- `AGENTS.md` already names the frontend checks (`npx tsc --noEmit`, `npx eslint <changed files>`, `npm test`) and expects `frontend/package.json` and `frontend/package-lock.json` to carry the version `0.1.0`.
- `megoocolab.toml` has three service sets (`test`, `migrate`, `image`), all for the backend. `tools/test-services/` holds their Compose files.
- There is no login yet (MITA-8), no Compose stack and no Caddy (MITA-4).

## Decisions

Answers from the owner:

1. **The sidebar has four groups**, in the PRD's order: Operate, Automate, Manage, Govern. Rejected: one flat list.
2. **In light mode, each ink shade that fails WCAG AA is darkened by the least that reaches 4.5 to 1 on every surface.** A contrast test fixes the values and keeps them passing. By my arithmetic the Knowledge Base's `cyan-ink` reaches only about 4.15 to 1 on `surface-2`, which is the background of the current sidebar item and of a hovered menu row. Rejected: the main text colour on tinted backgrounds, and keeping the Knowledge Base values as they are.
3. **The theme button has two states, light and dark.** The app follows the operating system until the person clicks. Rejected: MegooColab's three-step button (System, Dark, Light) and a menu with three choices.
4. **Unit tests plus a check of the built image.** A new `web` service set builds the frontend image and starts it, and a small test fetches pages from it. Rejected: unit tests only, and adding a Playwright browser test.

Decisions I made (say so if you want them changed):

5. **The setup follows MegooColab's frontend** (answers MC-Q8 and MC-Q9): Tailwind CSS v4, shadcn/ui in the `new-york` style, the theme as a `data-theme` attribute on `<html>`, fonts through `next/font/google`, ESLint's flat config with `eslint-config-next`, Vitest with jsdom and Testing Library, tests in `__tests__/` folders, and a three-stage `node:22-alpine` Dockerfile that runs as `node`. Two differences: shadcn components go to the default `src/components/ui/` (MegooColab keeps hand-built components there, MegooITAdmin has none), and the theme has two states (decision 3).
6. **The theme is a small module of our own (`src/lib/theme.ts`), not `next-themes`.** The task asks for a pre-paint script that reads `megoo-theme`, and MegooColab does the same in 33 lines.
7. **The sidebar's open or collapsed state is kept in shadcn's own `sidebar_state` cookie**, and the server reads it, so a reload shows the right width at once. It is a display preference, not a token. Rejected: `localStorage` with a second pre-paint script (shadcn's `Sidebar` takes its state from React, so the page would jump after hydration).
8. **Routes:** Dashboard is `/`. The others are `/servers`, `/sessions`, `/logs`, `/assistant`, `/playbooks`, `/approvals`, `/knowledge-base`, `/secrets`, `/scheduler`, `/reports`, `/audit` and `/settings`. Each is its own small page file, so a later task replaces one file.
9. **Every page is a placeholder**: the item's icon, its name, one line from the PRD on what the page will hold, and a "Not built yet" badge.
10. **An unknown address shows a 404 page inside the shell**, with a button back to the dashboard.
11. **The account menu shows a placeholder until login exists.** The component takes `user: { name, email } | null`, and the shell passes `null`: a generic user icon, the line "Sign-in is not available yet", and the disabled items "Profile and security" and "Sign out". MITA-8 passes the user and wires the items.
12. **The search box is a disabled button that looks like a search box**, with the text "Search…" and a `Ctrl K` hint. Below 768 px it is an icon. Nothing listens for Ctrl+K yet.
13. **Fonts come from `next/font/google`** (Geist, Geist Mono, Orbitron 700, Latin subset). Next.js downloads them during the build and the app serves them itself, so a browser never contacts Google. The build needs network access. Rejected: font files committed to the repository with their licence texts (more to maintain; worth revisiting only if builds must run offline).
14. **A test guards the "no tokens in browser storage" rule**: `localStorage` and `sessionStorage` may appear only in `src/lib/theme.ts`, and `document.cookie` only in shadcn's `sidebar.tsx`.
15. **Not added, because nothing uses them yet:** an API client, TanStack Query, the `/api` rewrite for `next dev`, `proxy.ts`, the `Command` palette, and a version label in the sidebar.

## Architecture

```text
megoocolab.toml                              changed: a fourth service set, web
tools/test-services/docker-compose.web.yml   new: the frontend image, port from WEB_PORT
AGENTS.md                                    changed: the Frontend line under Checks
frontend/
  .gitkeep                                   deleted
  package.json, package-lock.json            name megooitadmin-frontend, version 0.1.0
  tsconfig.json, next.config.ts, postcss.config.mjs, eslint.config.mjs, components.json
  vitest.config.mts, vitest.setup.ts         npm test
  vitest.image.config.mts                    npm run test:image
  Dockerfile, .dockerignore, .gitignore
  public/.gitkeep                            so the Dockerfile's COPY of public/ works
  image-tests/shell.test.ts                  the image check
  src/app/layout.tsx                         root layout: fonts, pre-paint script, metadata
  src/app/globals.css                        the only place a colour is written
  src/app/icon.svg                           favicon: the "M" mark
  src/app/(app)/layout.tsx                   reads the sidebar_state cookie, renders AppShell
  src/app/(app)/page.tsx                     Dashboard placeholder
  src/app/(app)/<route>/page.tsx             the 12 other placeholders
  src/app/(app)/[...rest]/page.tsx           calls notFound() for any other address
  src/app/(app)/not-found.tsx                the 404 page inside the shell
  src/lib/navigation.ts                      the four groups and 13 items, isActive(), findNavItem()
  src/lib/theme.ts                           storage key, read, set, pre-paint script
  src/lib/utils.ts, src/hooks/use-mobile.ts  written by the shadcn CLI
  src/components/ui/                         shadcn: sidebar, button, badge, dropdown-menu, tooltip, sheet,
                                             separator, input, skeleton
  src/components/shell/app-shell.tsx         SidebarProvider, AppSidebar, SiteHeader, <main>
  src/components/shell/app-sidebar.tsx       wordmark and the navigation
  src/components/shell/site-header.tsx       sidebar button, title, search, theme button, account menu
  src/components/shell/theme-switch.tsx
  src/components/shell/account-menu.tsx
  src/components/shell/search-placeholder.tsx
  src/components/shell/wordmark.tsx
  src/components/placeholder-page.tsx
```

The project is created with `create-next-app` (TypeScript, App Router, Tailwind, ESLint, `src/` directory, npm) and the shadcn CLI. Next.js is pinned to an exact 16.x version, with `eslint-config-next` at the same version. If `create-next-app` writes a `frontend/AGENTS.md` about Next.js 16's breaking changes, it stays.

How the pieces connect:

- **`src/app/layout.tsx`** (server) loads the three fonts as CSS variables, sets `<html lang="en" suppressHydrationWarning>`, and puts one inline `<script>` with `themeBootstrapScript` in `<head>`. Metadata: title template `%s · MegooITAdmin`. `viewport.themeColor` is `#f6f3ff` for light and `#0e0f13` for dark.
- **`src/app/(app)/layout.tsx`** (server) reads the `sidebar_state` cookie and renders `<AppShell defaultOpen={…}>`. The `(app)` group leaves room for MITA-8's sign-in pages outside the shell.
- **`AppShell`** renders a "Skip to content" link, shadcn's `SidebarProvider`, `AppSidebar`, and `SidebarInset` with `SiteHeader` and `<main id="main">`.
- **`AppSidebar`** (client) is `<Sidebar collapsible="icon">`:
  - The header holds the "M" mark and the wordmark `MEGOOITADMIN` in Orbitron 700, as a link to `/`. Collapsed, only the mark shows.
  - `<nav aria-label="Main">` holds one `SidebarGroup` per group, with its label and its items as links.
  - The current item has `aria-current="page"`, the tinted background, `cyan-ink` text in semibold and a cyan bar on its left, so it is never marked by colour alone. In dark mode it also has a cyan glow.
  - Collapsed, each item shows its name in a tooltip on hover and on keyboard focus, and the group labels become thin dividers.
  - Following a link closes the drawer on a small screen.
- **`SiteHeader`** (client) is sticky. From the left: the sidebar button (`PanelLeft`), a divider, the page title as `<h1>`, then the search placeholder, the theme button and the account menu on the right. The title comes from `findNavItem(pathname)`, or "Page not found".
- **Small screens.** Below 768 px (shadcn's breakpoint) the sidebar is a drawer: shadcn renders it in a `Sheet`, which brings the scrim, the focus trap and Escape. The header's sidebar button opens it.
- **Keyboard.** Ctrl+B (⌘B on macOS) collapses and opens the sidebar. This is built into shadcn's `SidebarProvider`.
- **`ThemeSwitch`** (client) is one icon button with the fixed label "Switch between light and dark". It renders both the `Sun` and the `Moon` icon and CSS shows one of them, so the server's HTML is right for either theme. A click calls `setTheme` with the other theme. While nothing is stored, it listens for the operating system's `prefers-color-scheme` change and follows it.
- **`src/lib/navigation.ts`** is the single source for the sidebar, the header title and the placeholder pages.

### Navigation

| Group | Item | Route | Lucide icon |
|---|---|---|---|
| Operate | Dashboard | `/` | `LayoutDashboard` |
| Operate | Servers | `/servers` | `Server` |
| Operate | Sessions | `/sessions` | `SquareTerminal` |
| Operate | Logs | `/logs` | `Logs` |
| Automate | Assistant | `/assistant` | `Bot` |
| Automate | Playbooks | `/playbooks` | `ListChecks` |
| Automate | Approvals | `/approvals` | `ShieldCheck` |
| Manage | Knowledge base | `/knowledge-base` | `BookOpen` |
| Manage | Secrets | `/secrets` | `KeyRound` |
| Manage | Scheduler | `/scheduler` | `CalendarClock` |
| Manage | Reports | `/reports` | `FileText` |
| Govern | Audit | `/audit` | `ScrollText` |
| Govern | Settings | `/settings` | `Settings` |

`isActive(pathname, href)`: `/` matches only `/`. Any other item matches its own route and anything below it (`/servers/12` marks Servers).

### Theme

`globals.css` follows MegooColab's file:

- **Tokens.** The Knowledge Base's tokens under their own names (`--bg`, `--surface`, `--surface-2`, `--line`, `--fg`, `--muted-foreground`, `--on-accent`, `--cyan`, `--pink`, `--green`, `--amber`, `--violet`, `--chart-1`, `--chart-2`, `--grid`) in `:root, :root[data-theme="light"]` and in `:root[data-theme="dark"]`. There is no `.dark` block. Tailwind's `dark:` variant is declared as `@custom-variant dark (&:where([data-theme=dark], [data-theme=dark] *))`.
- **Ink shades (decision 2).** Four text tones. Every other token keeps the Knowledge Base's value exactly.

  | Token | Light | Dark | Note |
  |---|---|---|---|
  | `--cyan-ink` | about `#007286` | `#22e4ff` | Knowledge Base: `#007a8f` |
  | `--green-ink` | about `#197725` | `#5bff9a` | Knowledge Base: `#1a7a27` |
  | `--pink-ink` | about `#cf004d` | `#ff3d81` | New. Pink as text. `--pink` stays `#d4004f` for fills and borders |
  | `--amber-ink` | about `#965b06` | `#ffe14d` | New. Amber as text. `--amber` stays `#a16207` for fills and borders |

  The light values are my estimates, worked by hand. The contrast test decides: if one fails, it is darkened in the smallest steps until it passes.
- **shadcn's variables** are mapped once, as the Knowledge Base's aliases say: `--background: var(--bg)`, `--primary: var(--cyan-ink)`, `--primary-foreground: var(--on-accent)`, `--accent: var(--surface-2)`, `--accent-foreground: var(--cyan-ink)`, `--destructive: var(--pink)`, `--border` and `--input: var(--line)`, `--ring: var(--cyan)`, and so on. `--radius` is `0.25rem`.
- **The sidebar's variables**, which MegooColab does not have: `--sidebar: var(--surface)`, `--sidebar-foreground: var(--fg)`, `--sidebar-primary: var(--cyan-ink)`, `--sidebar-primary-foreground: var(--on-accent)`, `--sidebar-accent: var(--surface-2)`, `--sidebar-accent-foreground: var(--cyan-ink)`, `--sidebar-border: var(--line)`, `--sidebar-ring: var(--cyan)`.
- **Depth.** Two tokens, `--shadow` (cards) and `--shadow-pop` (menus, the drawer). In light mode they are soft shadows. In dark mode they are cyan glows. Tailwind's shadow scale is mapped onto them in `@theme inline`, so shadcn's components follow the theme without edits. If the scale cannot be mapped cleanly, the classes are changed in the few generated components that cast a shadow. `--glow-cyan` (the mark, the current item's bar) is `none` in light mode.
- **Fonts.** `--font-sans` is Geist, `--font-mono` is Geist Mono and `--font-brand` is Orbitron, each with its system fallback. `h1` to `h3` have a letter spacing of `-0.01em`. Only the wordmark uses `font-brand`.
- **Capitals.** shadcn's `Button` gets `uppercase`, wide letter spacing and a semibold weight in its base classes, and `Badge` gets `uppercase`. The sidebar's group labels are small capitals too.
- **Background.** The page has the faint grid from the `--grid` token (22 px), as in MegooColab.
- **Reduced motion.** Under `prefers-reduced-motion`, the sidebar and the drawer do not animate.

## Data and interfaces

### `src/lib/theme.ts`

```ts
export type Theme = "light" | "dark";
export const THEME_STORAGE_KEY = "megoo-theme";
export function storedTheme(): Theme | null;   // null when nothing valid is stored or storage fails
export function systemTheme(): Theme;          // from prefers-color-scheme; "light" without matchMedia
export function setTheme(theme: Theme): void;  // stores it, then sets <html data-theme>
export const themeBootstrapScript: string;     // MegooColab's script, unchanged
```

The script: a stored `dark` or `light` wins. Otherwise the operating system's setting is used. It always writes `dark` or `light` to `document.documentElement.dataset.theme`.

### Browser storage and cookies

| Where | Key | Values | Written by |
|---|---|---|---|
| `localStorage` | `megoo-theme` | `light`, `dark`, or absent (follow the operating system) | `setTheme` |
| Cookie | `sidebar_state` | `true` or `false` | shadcn's `SidebarProvider` |

Nothing else is stored in the browser.

### `megoocolab.toml`, a new set

```toml
[services.web]
description = "The frontend image built from this checkout, for npm run test:image"
compose = ["tools/test-services/docker-compose.web.yml"]
ports = ["WEB_PORT"]

[services.web.env]
FRONTEND_IMAGE = "megooitadmin-frontend:${MEGOO_SERVICES_PROJECT}"
FRONTEND_URL = "http://localhost:${WEB_PORT}"
```

`docker-compose.web.yml` has one service, `frontend`: `build: ../../frontend`, `image: ${FRONTEND_IMAGE}`, port `127.0.0.1:${WEB_PORT}:3000`, and a healthcheck that fetches `/` with Node (the image has no curl).

### `frontend/Dockerfile`

MegooColab's file: three `node:22-alpine` stages. `deps` runs `npm ci`. `build` runs `npm run build`. `run` copies `public/`, `.next/standalone` and `.next/static`, sets `NODE_ENV=production`, `NEXT_TELEMETRY_DISABLED=1`, `PORT=3000` and `HOSTNAME=0.0.0.0`, runs as `node`, exposes 3000 and starts `node server.js`. `next.config.ts` holds only `output: "standalone"`. `.dockerignore`: `node_modules`, `.next`, `**/__tests__`, `image-tests`.

### `frontend/package.json` scripts

`dev`, `build`, `start`, `lint` (`eslint`), `test` (`vitest run`) and `test:image` (`vitest run --config vitest.image.config.mts`).

### `AGENTS.md`, the Frontend line under Checks

```markdown
- **Frontend** (`frontend/`): `npx tsc --noEmit`, `npx eslint <changed files>` and `npm test`, then the image
  check: `megoocolab-runner services run web -- npm run test:image`.
```

## Error handling and edge cases

- **Storage is blocked or throws.** The script and `storedTheme` catch the error and the app follows the operating system. The button still switches the theme, but only until the page is reloaded.
- **Something else is stored under `megoo-theme`** (for example `system`): it counts as nothing stored.
- **The operating system's setting changes** while nothing is stored: the app follows at once. After the person has chosen, it does not.
- **Two tabs.** A change in one tab reaches the other on its next load, not live.
- **No `sidebar_state` cookie, or any value other than `false`:** the sidebar starts open.
- **Reading the cookie makes the shell's pages render per request.** That is fine: they will all sit behind login.
- **The window crosses 768 px:** shadcn switches between the sidebar and the drawer, and an open drawer closes.
- **A short window:** the navigation scrolls inside the sidebar. The wordmark stays.
- **An unknown address** answers with status 404 and the shell around the 404 page.
- **No login yet.** Every page is public until MITA-8. The shell shows no data, so nothing leaks.
- **A build without network access** fails when Next.js fetches the fonts (decision 13).
- **A content security policy.** There is none yet. When one arrives, the inline script needs a nonce or a hash.
- **`megoocolab-runner services run web`** builds the image first, so the first run takes a few minutes.

## Testing

Tests are written first. Names read as sentences.

**`npm test`** (Vitest, jsdom, from `frontend/`):

- `lib/__tests__/navigation.test.ts`: the four groups and 13 items in the order, with the routes and icons of the table above. Routes are unique. `isActive` and `findNavItem` follow their rules.
- `lib/__tests__/theme.test.ts`:
  - `storedTheme` with `light`, `dark`, another value, nothing, and storage that throws;
  - `setTheme` stores the value and sets `data-theme`;
  - the pre-paint script, run as a string in jsdom, gives the right `data-theme` for each case: stored dark, stored light with a dark operating system, nothing stored with dark and with light, storage that throws.
- `app/__tests__/themeTokens.test.ts` (reads `globals.css` as text):
  - every token has the Knowledge Base's value, except the four ink shades in light mode;
  - shadcn's variables and the sidebar's variables map as listed above, and there is no `.dark` block;
  - **the contrast matrix**, in both themes: `fg`, `muted-foreground`, `cyan-ink`, `green-ink`, `pink-ink`, `amber-ink` and `violet` on `bg`, `surface` and `surface-2`, and `on-accent` on `cyan-ink` and on `pink`, each at least 4.5 to 1.
- `components/shell/__tests__/app-sidebar.test.tsx`: 13 links under four labels inside `<nav aria-label="Main">`. The current route has `aria-current="page"`. The wordmark links to `/` and uses the brand font.
- `components/shell/__tests__/app-shell.test.tsx`:
  - the sidebar button collapses and opens the sidebar and writes the cookie;
  - `defaultOpen={false}` renders it collapsed;
  - on a small screen the navigation is a dialog that opens from the button and closes when a link is followed;
  - the skip link points at `#main`.
- `components/shell/__tests__/site-header.test.tsx`: the title follows the route. An unknown route gives "Page not found". The search placeholder is disabled.
- `components/shell/__tests__/theme-switch.test.tsx`: a click switches `data-theme` and stores the choice. It still works when storage throws. It follows the operating system only while nothing is stored.
- `components/shell/__tests__/account-menu.test.tsx`: with no user, the menu opens, says that sign-in is not available yet, and both items are disabled.
- `components/__tests__/placeholder-page.test.tsx`: the name, the description and the badge.
- `components/ui/__tests__/caps.test.tsx`: `Button` and `Badge` are uppercase.
- `__tests__/storage.test.ts`: the rule of decision 14.

**`megoocolab-runner services run web -- npm run test:image`** (`image-tests/shell.test.ts`, plain HTTP against `FRONTEND_URL`):

- `GET /` gives 200, and the HTML has the wordmark and a link to each of the 13 routes.
- The pre-paint script is inside `<head>`, before `<body>`, and names `megoo-theme`.
- `GET /` with the cookie `sidebar_state=false` returns the sidebar collapsed.
- `GET /servers` gives 200 with "Servers" in the title.
- `GET /no-such-page` gives 404 and still has the navigation.
- Without `FRONTEND_URL` the test stops with a message that names the command above.

**Also run:** `npx tsc --noEmit` and `npx eslint .`. The image build runs `next build`.

The backend, security and release checks are skipped in this task: the backend does not change, and the other two parts are not in the repository yet. The implementer says so in the finish report.

## Out of scope

- Login, MFA, the real account menu and redirecting people who are not signed in (MITA-8). Hiding menu items by role (MITA-9).
- The search itself, the Ctrl+K palette and shadcn's `Command` (Phase 6). The pending-count badge on Approvals (Phase 4).
- The content of the 13 pages, xterm.js and `guacamole-common-js`.
- An API client, TanStack Query, the `/api` rewrite for `next dev`, WebSockets.
- The `frontend` service in the Compose stack and Caddy (MITA-4). CI (MITA-12).
- A browser test with Playwright, and a "System" choice in the theme button (both rejected above).
- Keeping the theme or the sidebar state on the server.
- A content security policy and a nonce for the inline script.
- Changing the Knowledge Base's Cyberpunk Theme page to the darker ink shades.
- Any change to the backend, `README.md` or `docs/releasing.md`.
