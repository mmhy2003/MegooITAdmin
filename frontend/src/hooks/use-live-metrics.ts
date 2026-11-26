"use client";

import { useEffect, useRef, useState } from "react";
import { LiveSocket, type LiveStatus, type LiveView } from "@/lib/live-socket";
import type { LiveMessage } from "@/lib/metrics";

export type LiveMetricsOptions = {
  view: LiveView;
  serverIds: string[];
  onMessage: (m: LiveMessage) => void;
  /** Called after every (re)open, so the page can read again over REST whatever it missed. */
  onOpen: () => void;
  enabled?: boolean;
};

/**
 * One metrics socket for the page while `enabled`, subscribed to `serverIds`. A change of servers sends a new
 * subscription on the same socket, and new callbacks never reconnect it.
 */
export function useLiveMetrics({ view, serverIds, onMessage, onOpen, enabled = true }: LiveMetricsOptions): LiveStatus {
  const [status, setStatus] = useState<LiveStatus>("connecting");
  const socket = useRef<LiveSocket | null>(null);
  const callbacks = useRef({ onMessage, onOpen });
  const subscription = useRef({ view, serverIds });
  useEffect(() => {
    callbacks.current = { onMessage, onOpen };
  }, [onMessage, onOpen]);

  useEffect(() => {
    if (!enabled) return;
    const live = new LiveSocket({
      onMessage: (m) => callbacks.current.onMessage(m),
      onOpen: () => callbacks.current.onOpen(),
      onStatus: setStatus,
    });
    live.subscribe(subscription.current.view, subscription.current.serverIds);
    socket.current = live;
    return () => {
      live.close();
      socket.current = null;
      setStatus("paused");
    };
  }, [enabled]);

  const key = serverIds.join(",");
  useEffect(() => {
    subscription.current = { view, serverIds: key === "" ? [] : key.split(",") };
    socket.current?.subscribe(subscription.current.view, subscription.current.serverIds);
  }, [view, key]);

  return status;
}
