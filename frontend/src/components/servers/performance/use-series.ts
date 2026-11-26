"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useRefresh } from "@/hooks/use-refresh";
import { apiFetch } from "@/lib/api";
import {
  appendSample,
  HISTORY_REFRESH_MS,
  LIVE_WINDOW_MS,
  type RangeName,
  type SampleMessage,
  type SeriesAnswer,
} from "@/lib/metrics";

export type SeriesState = { answer: SeriesAnswer | null; loading: boolean; failed: boolean; retry: () => void };

/**
 * The series of `metrics` on one server for a range. A new range, server or `refill` reads again in the foreground
 * and keeps the previous answer until the new one arrives. In live, each sample of this server is appended; a
 * history range re-reads in the background every minute, and a failed background read keeps everything.
 */
export function useSeries(
  serverId: string,
  metrics: string[],
  range: RangeName,
  sample: SampleMessage | null,
  refill: number,
): SeriesState {
  const [answer, setAnswer] = useState<SeriesAnswer | null>(null);
  const [attempt, setAttempt] = useState(0);
  // The latest foreground read that answered or failed; loading is any other read being the current one.
  const [settled, setSettled] = useState<{ key: string; failed: boolean } | null>(null);
  // Each foreground read takes a number; an answer is applied only while its read is still the latest.
  const reads = useRef(0);
  const path = `/servers/${serverId}/metrics?range=${range}&` + metrics.map((m) => "metric=" + m).join("&");
  const key = `${path}#${refill}#${attempt}`;
  const latestMetrics = useRef(metrics);
  useEffect(() => {
    latestMetrics.current = metrics;
  });

  useEffect(() => {
    const read = ++reads.current;
    apiFetch<SeriesAnswer>(path, { background: false }).then(
      (next) => {
        if (read !== reads.current) return;
        setAnswer(next);
        setSettled({ key, failed: false });
      },
      () => {
        if (read === reads.current) setSettled({ key, failed: true });
      },
    );
  }, [path, key]);

  useEffect(() => {
    if (sample === null || sample.server_id !== serverId) return;
    setAnswer((current) =>
      current?.range === "live"
        ? { ...current, series: appendSample(current.series, sample, latestMetrics.current, LIVE_WINDOW_MS) }
        : current,
    );
  }, [sample, serverId]);

  // A background re-read applies only if no foreground read started meanwhile, and fails silently.
  const background = useCallback(() => {
    const read = reads.current;
    apiFetch<SeriesAnswer>(path, { background: true }).then(
      (next) => {
        if (read === reads.current) setAnswer(next);
      },
      () => {},
    );
  }, [path]);
  useRefresh(background, range !== "live", HISTORY_REFRESH_MS);

  const retry = useCallback(() => setAttempt((a) => a + 1), []);
  const loading = settled?.key !== key;
  return { answer, loading, failed: !loading && settled.failed, retry };
}
