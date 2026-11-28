"use client";

import { useEffect, useMemo, useRef, useState, useSyncExternalStore, type ReactNode } from "react";
import { LogPane } from "@/components/logs/log-pane";
import { LogToolbar } from "@/components/logs/log-toolbar";
import { useFiltered } from "@/components/logs/use-filtered";
import { Button } from "@/components/ui/button";
import { apiFetch } from "@/lib/api";
import type { Container } from "@/lib/checks";
import { Merger } from "@/lib/logs/merge";
import { LogSocket } from "@/lib/logs/socket";
import { encodeSource, sourceLabel, swapContainers, wire, type ViewState } from "@/lib/logs/sources";
import { LogStore } from "@/lib/logs/store";
import type { Server } from "@/lib/servers";

/** The tag colours of a merged pane: `log-tag-0` to `log-tag-5`, by the source's index. */
const TONES = 6;
/** The title of a source whose server is not among those the person sees. */
const UNKNOWN_SERVER = "Unknown server";

/** The socket of the mount that is current, for the store and the activity handlers to reach. */
class SocketLink {
  socket: LogSocket | null = null;

  attach(socket: LogSocket | null): void {
    this.socket = socket;
  }
}

/**
 * The live log viewer: one socket and one store for the sources of `state`, shown side by side or merged, under the
 * toolbar of its settings. Every change of sources or settings goes out through `onChange`, including a recreated
 * container found again by its name, which is said before the sources are subscribed to.
 */
export function LogViewer({ state, onChange, servers, extra }: {
  state: ViewState;
  onChange: (next: ViewState) => void;
  servers: Server[];
  extra?: ReactNode;
}) {
  // The store outlives a remount (React's strict mode mounts twice); each mount opens its own socket into `link`.
  const [{ store, link, subscribe, read }] = useState(() => {
    const link = new SocketLink();
    const store = new LogStore({ onWanted: (sources) => link.socket?.subscribe(sources.map(wire)) });
    return {
      store,
      link,
      subscribe: (listener: () => void) => store.subscribe(listener),
      read: () => store.snapshot(),
    };
  });
  const [merger] = useState(() => new Merger());
  // Each server's containers, read once per mount; null when the read failed.
  const [listings] = useState(() => new Map<string, Promise<Container[] | null>>());
  const snapshot = useSyncExternalStore(subscribe, read, read);

  const latest = useRef({ state, onChange });
  useEffect(() => {
    latest.current = { state, onChange };
  }, [state, onChange]);

  useEffect(() => {
    const socket = new LogSocket({
      onMessage: (m) => store.handle(m),
      onStatus: (s) => store.socketStatus(s),
      onOpen: () => store.socketOpened(),
    });
    link.attach(socket);
    socket.subscribe(store.wanted().map(wire));
    return () => {
      socket.close();
      link.attach(null);
      // Drops every source with its retry timers; the next mount sets them again.
      store.setSources([]);
    };
  }, [store, link]);

  useEffect(() => {
    const sources = state.sources;
    const ids = [...new Set(sources.filter((s) => s.kind === "container").map((s) => s.server_id))];
    if (ids.length === 0) {
      store.setSources(sources);
      return;
    }
    let current = true;
    const containersOf = (id: string) => {
      let listing = listings.get(id);
      if (listing === undefined) {
        listing = apiFetch<Container[]>(`/servers/${id}/containers`).catch(() => null);
        listings.set(id, listing);
      }
      return listing.then((list) => [id, list] as const);
    };
    void Promise.all(ids.map(containersOf)).then((pairs) => {
      if (!current) return;
      const known = new Map<string, Container[]>();
      for (const [id, list] of pairs) if (list !== null) known.set(id, list);
      const swapped = swapContainers(sources, known);
      if (swapped.changed) latest.current.onChange({ ...latest.current.state, sources: swapped.sources });
      store.setSources(swapped.sources);
    });
    return () => {
      current = false;
    };
  }, [state.sources, store, listings]);

  const { settings } = state;
  const merged = settings.layout === "merged";
  const { entries } = snapshot;
  const names = useMemo(() => new Map(servers.map((s) => [s.id, s.name])), [servers]);
  const serverName = (id: string) => names.get(id) ?? UNKNOWN_SERVER;
  // A merged pane's label and coloured tag of each source: its server and what it follows.
  const tagged = useMemo(() => {
    const labels = new Map<string, string>();
    const tags = new Map<string, { text: string; tone: number }>();
    entries.forEach((e, i) => {
      const text = `${names.get(e.source.server_id) ?? UNKNOWN_SERVER} · ${sourceLabel(e.source)}`;
      labels.set(e.id, text);
      tags.set(e.id, { text, tone: i % TONES });
    });
    return { labels, tags };
  }, [entries, names]);
  const lists = useMemo(
    () => (merged ? [merger.update(entries)] : entries.map((e) => e.rows)),
    [merged, merger, entries],
  );
  const filtered = useFiltered(lists, settings);

  function remove(id: string) {
    onChange({ ...state, sources: state.sources.filter((s) => encodeSource(s) !== id) });
  }

  const active = () => link.socket?.active();
  const pane = {
    socket: snapshot.socket,
    utc: settings.utc,
    wrap: settings.wrap,
    filter: filtered.filter,
    onRetryNow: (id: string) => store.retryNow(id),
    onReconnect: (id: string) => store.reconnect(id),
  };

  return (
    <div className="flex flex-col gap-4" onPointerDown={active} onKeyDown={active} onWheel={active}
      onScrollCapture={active}>
      <LogToolbar settings={settings} onSettings={(next) => onChange({ ...state, settings: next })}
        matched={filtered.matched} total={filtered.total} extra={extra} />
      {snapshot.idle && (
        <div className="flex flex-wrap items-center gap-2 rounded-md border px-3 py-2 text-sm">
          <p className="min-w-0 flex-1">Paused after 30 minutes without activity.</p>
          <Button size="sm" variant="outline" onClick={() => store.resume()}>Resume</Button>
        </div>
      )}
      {merged ? (
        entries.length > 0 && (
          <LogPane {...pane} title="Merged" entry={null} entries={entries} rows={filtered.lists[0] ?? []}
            merged={tagged} downloadParts={["merged"]} />
        )
      ) : (
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {entries.map((entry, i) => {
            const title = serverName(entry.source.server_id);
            return (
              <LogPane key={entry.id} {...pane} title={title} entry={entry} entries={[entry]}
                rows={filtered.lists[i] ?? []} merged={null} onRemove={remove}
                downloadParts={[title, sourceLabel(entry.source)]} />
            );
          })}
        </div>
      )}
    </div>
  );
}
