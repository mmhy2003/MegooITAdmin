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
