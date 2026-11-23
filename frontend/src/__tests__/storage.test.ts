import { readdirSync, readFileSync, statSync } from "node:fs";
import { dirname, join, relative } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

// Not new URL("../..", import.meta.url): Vite rewrites that pattern into an asset URL.
const root = join(dirname(fileURLToPath(import.meta.url)), "..", ".."); // frontend/
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
