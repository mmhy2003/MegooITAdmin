import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { REFRESH_EVERY_MS, useRefresh } from "@/hooks/use-refresh";

let visibility: DocumentVisibilityState = "visible";
Object.defineProperty(document, "visibilityState", { configurable: true, get: () => visibility });

function show(state: DocumentVisibilityState) {
  visibility = state;
  act(() => {
    document.dispatchEvent(new Event("visibilitychange"));
  });
}

function advance(ms: number) {
  act(() => {
    vi.advanceTimersByTime(ms);
  });
}

describe("useRefresh", () => {
  beforeEach(() => {
    visibility = "visible";
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("calls refresh every 15 seconds", () => {
    expect(REFRESH_EVERY_MS).toBe(15_000);
    const refresh = vi.fn();
    renderHook(() => useRefresh(refresh, true));
    advance(14_999);
    expect(refresh).toHaveBeenCalledTimes(0);
    advance(1);
    expect(refresh).toHaveBeenCalledTimes(1);
    advance(15_000);
    expect(refresh).toHaveBeenCalledTimes(2);
  });

  it("sends nothing while the tab is hidden", () => {
    const refresh = vi.fn();
    renderHook(() => useRefresh(refresh, true));
    show("hidden");
    advance(60_000);
    expect(refresh).not.toHaveBeenCalled();
  });

  it("refreshes once when the tab becomes visible again, then every 15 seconds", () => {
    const refresh = vi.fn();
    renderHook(() => useRefresh(refresh, true));
    show("hidden");
    advance(60_000);
    show("visible");
    expect(refresh).toHaveBeenCalledTimes(1);
    advance(15_000);
    expect(refresh).toHaveBeenCalledTimes(2);
  });

  it("does nothing while inactive", () => {
    const refresh = vi.fn();
    const { rerender } = renderHook(({ active }) => useRefresh(refresh, active), {
      initialProps: { active: false },
    });
    advance(60_000);
    show("visible");
    expect(refresh).not.toHaveBeenCalled();
    rerender({ active: true });
    advance(15_000);
    expect(refresh).toHaveBeenCalledTimes(1);
  });

  it("stops after unmount", () => {
    const refresh = vi.fn();
    const { unmount } = renderHook(() => useRefresh(refresh, true));
    unmount();
    advance(60_000);
    show("visible");
    expect(refresh).not.toHaveBeenCalled();
  });

  it("calls the newest refresh", () => {
    const first = vi.fn();
    const second = vi.fn();
    const { rerender } = renderHook(({ refresh }) => useRefresh(refresh, true), {
      initialProps: { refresh: first },
    });
    rerender({ refresh: second });
    advance(15_000);
    expect(first).not.toHaveBeenCalled();
    expect(second).toHaveBeenCalledTimes(1);
  });
});
