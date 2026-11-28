import { vi } from "vitest";

/**
 * jsdom lays nothing out, so every size is 0. Give scroll containers (`data-log-scroll`) `width` by `height`, and
 * every other element the height of one row. A scroll container's scrollHeight is the height its first child (the
 * list's sizer) is styled with. Returns a function that puts the real properties back.
 */
export function mockElementSize(width = 800, height = 400, row = 20): () => void {
  const isScroll = (el: HTMLElement) => el.hasAttribute("data-log-scroll");
  const heightOf = (el: HTMLElement) => (isScroll(el) ? height : row);
  const spies = [
    vi.spyOn(HTMLElement.prototype, "getBoundingClientRect").mockImplementation(function (this: HTMLElement) {
      return new DOMRect(0, 0, width, heightOf(this));
    }),
    vi.spyOn(HTMLElement.prototype, "offsetWidth", "get").mockImplementation(() => width),
    vi.spyOn(HTMLElement.prototype, "offsetHeight", "get").mockImplementation(function (this: HTMLElement) {
      return heightOf(this);
    }),
    vi.spyOn(HTMLElement.prototype, "clientHeight", "get").mockImplementation(function (this: HTMLElement) {
      return heightOf(this);
    }),
    vi.spyOn(HTMLElement.prototype, "scrollHeight", "get").mockImplementation(function (this: HTMLElement) {
      if (!isScroll(this)) return row;
      const sizer = this.firstElementChild as HTMLElement | null;
      return Math.max(height, parseFloat(sizer?.style.height ?? "") || 0);
    }),
  ];
  return () => spies.forEach((spy) => spy.mockRestore());
}
