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
// Tests set the route with vi.mocked(usePathname).mockReturnValue(...), and the query with useSearchParams.
vi.mock("next/navigation", () => ({
  usePathname: vi.fn(() => "/"),
  notFound: vi.fn(),
  useRouter: vi.fn(() => ({ push: vi.fn(), replace: vi.fn(), refresh: vi.fn() })),
  useSearchParams: vi.fn(() => new URLSearchParams()),
}));

// Files marked `// @vitest-environment node` have no DOM: the DOM set-up below skips them.
const hasDom = typeof window !== "undefined";

beforeEach(() => {
  if (!hasDom) return;
  mockMatchMedia();
  localStorage.clear();
  delete document.documentElement.dataset.theme;
});

afterEach(() => {
  if (hasDom) cleanup();
  vi.restoreAllMocks();
});

// jsdom has no ResizeObserver or pointer capture; Radix popups use them.
if (hasDom) {
  if (!("ResizeObserver" in globalThis)) {
    globalThis.ResizeObserver = class { observe() {} unobserve() {} disconnect() {} } as unknown as typeof ResizeObserver;
  }
  Element.prototype.hasPointerCapture ??= () => false;
  Element.prototype.releasePointerCapture ??= () => {};
  Element.prototype.scrollIntoView ??= () => {};
}
