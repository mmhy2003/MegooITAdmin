import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { FakeWebSocket, installFakeWebSocket } from "@/__tests__/helpers/fake-websocket";
import { useLiveMetrics } from "@/hooks/use-live-metrics";
import type { LiveView } from "@/lib/live-socket";
import type { LiveMessage } from "@/lib/metrics";

vi.mock("@/lib/auth/navigate", () => ({ goTo: vi.fn() }));

type Props = {
  view: LiveView;
  serverIds: string[];
  onMessage: (m: LiveMessage) => void;
  onOpen: () => void;
  enabled?: boolean;
};

const subscribed = { type: "subscribed", server_ids: ["a"] } as unknown as LiveMessage;

function render(initial: Partial<Props> = {}) {
  const initialProps: Props = { view: "overview", serverIds: ["a"], onMessage: vi.fn(), onOpen: vi.fn(), ...initial };
  return renderHook((props: Props) => useLiveMetrics(props), { initialProps });
}

function only(): FakeWebSocket {
  expect(FakeWebSocket.instances).toHaveLength(1);
  return FakeWebSocket.instances[0];
}

beforeEach(() => {
  vi.useFakeTimers();
  installFakeWebSocket();
  Object.defineProperty(document, "visibilityState", { configurable: true, get: () => "visible" });
});

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe("useLiveMetrics", () => {
  it("opens one socket and reports connecting, then live", () => {
    const { result } = render();
    const socket = only();
    expect(result.current).toBe("connecting");
    act(() => socket.open());
    expect(result.current).toBe("live");
    expect(socket.sent).toEqual([{ type: "subscribe", view: "overview", server_ids: ["a"] }]);
  });

  it("subscribes again on the same socket when the servers change", () => {
    const { rerender } = render();
    const socket = only();
    act(() => socket.open());
    rerender({ view: "overview", serverIds: ["c", "b"], onMessage: vi.fn(), onOpen: vi.fn() });
    expect(only()).toBe(socket);
    expect(socket.sent).toEqual([
      { type: "subscribe", view: "overview", server_ids: ["a"] },
      { type: "subscribe", view: "overview", server_ids: ["b", "c"] },
    ]);
  });

  it("hands messages to the newest callback without reconnecting", () => {
    const first = vi.fn();
    const second = vi.fn();
    const { rerender } = render({ onMessage: first });
    const socket = only();
    act(() => socket.open());
    rerender({ view: "overview", serverIds: ["a"], onMessage: second, onOpen: vi.fn() });
    act(() => socket.receive(subscribed));
    expect(only()).toBe(socket);
    expect(first).not.toHaveBeenCalled();
    expect(second).toHaveBeenCalledWith(subscribed);
  });

  it("calls onOpen on every open", () => {
    const onOpen = vi.fn();
    render({ onOpen });
    act(() => FakeWebSocket.instances[0].open());
    expect(onOpen).toHaveBeenCalledTimes(1);
    act(() => FakeWebSocket.instances[0].drop(1011));
    act(() => {
      vi.advanceTimersByTime(1000);
    });
    expect(FakeWebSocket.instances).toHaveLength(2);
    act(() => FakeWebSocket.instances[1].open());
    expect(onOpen).toHaveBeenCalledTimes(2);
  });

  it("opens no socket while disabled, and closes it when disabled", () => {
    const props: Props = { view: "overview", serverIds: ["a"], onMessage: vi.fn(), onOpen: vi.fn() };
    const { rerender } = render({ ...props, enabled: false });
    expect(FakeWebSocket.instances).toHaveLength(0);
    rerender({ ...props, enabled: true });
    const socket = only();
    rerender({ ...props, enabled: false });
    expect(socket.closedByClient).toBe(true);
    act(() => {
      vi.advanceTimersByTime(60_000);
    });
    expect(FakeWebSocket.instances).toHaveLength(1);
  });

  it("closes the socket on unmount", () => {
    const { unmount } = render();
    const socket = only();
    unmount();
    expect(socket.closedByClient).toBe(true);
  });
});
