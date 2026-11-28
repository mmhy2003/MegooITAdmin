"use client";

import { DownloadIcon, XIcon } from "lucide-react";
import { useState, useSyncExternalStore } from "react";
import { LogList } from "@/components/logs/log-list";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { downloadName, downloadText } from "@/lib/logs/download";
import type { CompiledFilter } from "@/lib/logs/filter";
import { sourceLabel } from "@/lib/logs/sources";
import { RETRY_MS, type PaneState, type Row, type SocketState, type SourceEntry } from "@/lib/logs/store";

/** Why a source was refused or ended, in words. `{status}` is the exit status of the command. */
export const REASONS: Record<string, string> = {
  not_found: "This server does not exist any more, or you cannot see it.",
  forbidden: "You do not hold View logs on this server.",
  not_allowed: "This file matches none of the group's log file patterns.",
  not_an_ssh_server: "Only Linux servers stream logs.",
  host_key_not_pinned: "The server's host key is not pinned yet.",
  host_key_changed: "The server's host key has changed. An Admin must review it.",
  too_many_sources: "This server already streams 8 sources, the most allowed. Remove one first.",
  worker_unavailable: "The logs worker is not answering.",
  worker_restarted: "The logs worker restarted.",
  unreachable: "The server is not answering.",
  ssh_error: "The SSH connection failed.",
  exited: "The command ended with status {status}.",
  not_readable: "The file does not exist, or cannot be read.",
  not_available: "This source is not available on this server.",
  denied: "sudo refused megoo-ctl on this server. Run megoo-setup.sh on it again.",
  key_refused: "The server refused the platform's key.",
};

type Tag = { text: string; tone: number };

const REVOKE_AFTER_MS = 1000;

function reasonText(reason: string, status: number | null = null): string {
  const text = REASONS[reason];
  if (text === undefined) return `The stream ended (${reason}).`;
  return text.replace("{status}", status === null ? "unknown" : String(status));
}

const BADGES: Record<PaneState["state"], string> = {
  opening: "Connecting",
  live: "Live",
  retrying: "Retrying",
  ended: "Ended",
  denied: "Refused",
  idle: "Paused",
};

/** The badge of a pane: the socket's reconnect first, then the first source that is not live, then Live or Paused. */
function badgeOf(entries: SourceEntry[], socket: SocketState, paused: boolean): string {
  if (socket === "reconnecting") return "Reconnecting";
  const other = entries.find((e) => e.state.state !== "live");
  if (other) return BADGES[other.state.state];
  return paused ? "Paused" : "Live";
}

/**
 * A clock that ticks each second while someone counts down. It is read afresh when a countdown subscribes, and React
 * reads it again right after subscribing and draws before paint, so a countdown never starts from an old time.
 */
const clock = { now: Date.now(), listeners: new Set<() => void>(), timer: null as ReturnType<typeof setInterval> | null };

function subscribeClock(listener: () => void): () => void {
  clock.now = Date.now();
  clock.listeners.add(listener);
  clock.timer ??= setInterval(() => {
    clock.now = Date.now();
    clock.listeners.forEach((l) => l());
  }, 1000);
  return () => {
    clock.listeners.delete(listener);
    if (clock.listeners.size === 0 && clock.timer !== null) {
      clearInterval(clock.timer);
      clock.timer = null;
    }
  };
}

const stopped = () => () => {};
const readClock = () => clock.now;

/** Epoch ms, again each second while `on`: what a countdown draws from. */
function useNow(on: boolean): number {
  return useSyncExternalStore(on ? subscribeClock : stopped, readClock, readClock);
}

/** What a source that is not live says, with the button that acts on it. */
function StateMessage({ entry, prefix, now, onRetryNow, onReconnect, onManagePatterns }: {
  entry: SourceEntry;
  prefix: string;
  now: number;
  onRetryNow: (id: string) => void;
  onReconnect: (id: string) => void;
  onManagePatterns?: (id: string) => void;
}) {
  const { state } = entry;
  if (state.state !== "retrying" && state.state !== "ended" && state.state !== "denied") return null;
  let text = reasonText(state.reason, state.state === "ended" ? state.status : null);
  if (state.state === "retrying") {
    const seconds = Math.max(0, Math.ceil((state.at - now) / 1000));
    text = `${text} Trying again in ${seconds} s (${state.attempt} of ${RETRY_MS.length}).`;
  }
  return (
    <div className="flex flex-wrap items-center gap-2 border-b px-3 py-2 text-sm text-muted-foreground">
      <p className="min-w-0 flex-1">{prefix}{text}</p>
      {state.state === "retrying" && (
        <Button size="xs" variant="outline" onClick={() => onRetryNow(entry.id)}>Try now</Button>
      )}
      {state.state === "ended" && (
        <Button size="xs" variant="outline" onClick={() => onReconnect(entry.id)}>Reconnect</Button>
      )}
      {state.reason === "not_allowed" && onManagePatterns && (
        <Button size="xs" variant="outline" onClick={() => onManagePatterns(entry.id)}>Manage patterns</Button>
      )}
    </div>
  );
}

/**
 * One pane: a header with the server, the source, its state and the lines skipped, what a source that is not live
 * says, and its rows. A pane always holds its rows, whatever its state. A merged pane (`entry` null) shows the rows of
 * `entries` with their tags, and downloads them with their labels.
 */
export function LogPane({
  title, entry, entries, rows, socket, utc, wrap, filter, merged, onRemove, onRetryNow, onReconnect, onManagePatterns,
  downloadParts,
}: {
  title: string;
  entry: SourceEntry | null;
  entries: SourceEntry[];
  rows: Row[];
  socket: SocketState;
  utc: boolean;
  wrap: boolean;
  filter: CompiledFilter | null;
  merged: { labels: Map<string, string>; tags: Map<string, Tag> } | null;
  onRemove?: (id: string) => void;
  onRetryNow: (id: string) => void;
  onReconnect: (id: string) => void;
  onManagePatterns?: (id: string) => void;
  downloadParts: string[];
}) {
  const [paused, setPaused] = useState(false);
  const shown = entry ? [entry] : entries;
  const now = useNow(shown.some((e) => e.state.state === "retrying"));
  const heading = entry ? title : `Merged · ${entries.length} sources`;
  const label = entry ? sourceLabel(entry.source) : heading;
  const skipped = shown.reduce((sum, e) => sum + e.skipped, 0);
  const badge = badgeOf(shown, socket, paused);

  function download() {
    const text = downloadText(rows, { utc, labels: merged?.labels ?? null });
    const url = URL.createObjectURL(new Blob([text], { type: "text/plain;charset=utf-8" }));
    const a = document.createElement("a");
    a.href = url;
    a.download = downloadName(downloadParts, new Date());
    a.click();
    // Some browsers start the download after click() returns: revoking at once could cancel it.
    setTimeout(() => URL.revokeObjectURL(url), REVOKE_AFTER_MS);
  }

  return (
    <Card className="h-[30rem] min-w-0 gap-0 overflow-hidden py-0">
      <div className="flex items-center gap-2 border-b px-3 py-2">
        <div className="flex min-w-0 flex-1 items-baseline gap-2">
          <span className="truncate font-semibold">{heading}</span>
          {entry && <span className="truncate text-sm text-muted-foreground">{label}</span>}
        </div>
        {skipped > 0 && (
          <span className="shrink-0 text-xs text-muted-foreground">{skipped.toLocaleString("en-US")} skipped</span>
        )}
        <Badge variant={badge === "Live" ? "default" : "secondary"}>{badge}</Badge>
        <Button size="icon-xs" variant="ghost" aria-label={`Download ${label}`} title="Download" onClick={download}>
          <DownloadIcon />
        </Button>
        {entry && onRemove && (
          <Button size="icon-xs" variant="ghost" aria-label={`Remove ${label}`} title="Remove"
            onClick={() => onRemove(entry.id)}>
            <XIcon />
          </Button>
        )}
      </div>
      {shown.map((e) => (
        <StateMessage key={e.id} entry={e} prefix={entry ? "" : `${merged?.labels.get(e.id) ?? sourceLabel(e.source)}: `}
          now={now} onRetryNow={onRetryNow} onReconnect={onReconnect} onManagePatterns={onManagePatterns} />
      ))}
      <LogList rows={rows} utc={utc} wrap={wrap} filter={filter} tags={merged?.tags ?? null}
        label={entry ? `${title} · ${label}` : heading} onPaused={setPaused} />
    </Card>
  );
}
