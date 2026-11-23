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
