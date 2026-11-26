"use client";

import { useEffect, useRef } from "react";

export const REFRESH_EVERY_MS = 15_000;

/**
 * Calls `refresh` every `everyMs` (15 seconds by default) while the tab is visible and `active` is true, and once when
 * the tab becomes visible again. A hidden tab sends nothing.
 */
export function useRefresh(refresh: () => void, active: boolean, everyMs: number = REFRESH_EVERY_MS): void {
  const latest = useRef(refresh);
  useEffect(() => {
    latest.current = refresh;
  }, [refresh]);

  useEffect(() => {
    if (!active) return;
    let timer: ReturnType<typeof setInterval> | undefined;
    const start = () => {
      timer = setInterval(() => latest.current(), everyMs);
    };
    const stop = () => {
      clearInterval(timer);
      timer = undefined;
    };
    function changed() {
      stop();
      if (document.visibilityState === "visible") {
        latest.current();
        start();
      }
    }
    if (document.visibilityState === "visible") start();
    document.addEventListener("visibilitychange", changed);
    return () => {
      stop();
      document.removeEventListener("visibilitychange", changed);
    };
  }, [active, everyMs]);
}
