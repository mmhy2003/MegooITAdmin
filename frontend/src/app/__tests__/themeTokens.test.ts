import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

const css = readFileSync(join(import.meta.dirname, "../globals.css"), "utf8");

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
