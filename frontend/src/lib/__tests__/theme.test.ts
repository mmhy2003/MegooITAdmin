import { describe, expect, it, vi } from "vitest";
import { mockMatchMedia } from "@/__tests__/helpers/match-media";
import { setTheme, storedTheme, systemTheme, THEME_STORAGE_KEY, themeBootstrapScript } from "@/lib/theme";

function blockStorage(method: "getItem" | "setItem") {
  vi.spyOn(Storage.prototype, method).mockImplementation(() => {
    throw new Error("blocked");
  });
}

function runBootstrap() {
  new Function(themeBootstrapScript)();
  return document.documentElement.dataset.theme;
}

describe("storedTheme", () => {
  it("returns the stored light or dark", () => {
    localStorage.setItem("megoo-theme", "light");
    expect(storedTheme()).toBe("light");
    localStorage.setItem("megoo-theme", "dark");
    expect(storedTheme()).toBe("dark");
  });

  it("returns null for system, nothing stored or blocked storage", () => {
    expect(storedTheme()).toBeNull();
    localStorage.setItem("megoo-theme", "system");
    expect(storedTheme()).toBeNull();
    localStorage.setItem("megoo-theme", "dark");
    blockStorage("getItem");
    expect(storedTheme()).toBeNull();
  });
});

describe("systemTheme", () => {
  it("is dark with a dark OS", () => {
    mockMatchMedia({ dark: true });
    expect(systemTheme()).toBe("dark");
  });

  it("is light with a light OS", () => {
    expect(systemTheme()).toBe("light");
  });
});

describe("setTheme", () => {
  it("stores the theme and applies it", () => {
    setTheme("dark");
    expect(localStorage.getItem("megoo-theme")).toBe("dark");
    expect(document.documentElement.dataset.theme).toBe("dark");
  });

  it("still applies the theme when storage is blocked", () => {
    blockStorage("setItem");
    setTheme("dark");
    expect(document.documentElement.dataset.theme).toBe("dark");
  });
});

describe("themeBootstrapScript", () => {
  it("applies a stored dark", () => {
    localStorage.setItem("megoo-theme", "dark");
    expect(runBootstrap()).toBe("dark");
  });

  it("prefers a stored light over a dark OS", () => {
    mockMatchMedia({ dark: true });
    localStorage.setItem("megoo-theme", "light");
    expect(runBootstrap()).toBe("light");
  });

  it("follows a dark OS when nothing is stored", () => {
    mockMatchMedia({ dark: true });
    expect(runBootstrap()).toBe("dark");
  });

  it("follows a light OS when nothing is stored", () => {
    expect(runBootstrap()).toBe("light");
  });

  it("follows the OS when storage is blocked", () => {
    mockMatchMedia({ dark: true });
    blockStorage("getItem");
    expect(runBootstrap()).toBe("dark");
  });

  it("reads the megoo-theme key", () => {
    expect(THEME_STORAGE_KEY).toBe("megoo-theme");
    expect(themeBootstrapScript).toContain("megoo-theme");
  });
});
