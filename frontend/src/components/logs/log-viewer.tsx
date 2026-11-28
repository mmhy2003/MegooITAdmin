"use client";

import { useEffect, useMemo, useRef, useState, useSyncExternalStore, type ReactNode } from "react";
import { LogPane } from "@/components/logs/log-pane";
import { LogToolbar } from "@/components/logs/log-toolbar";
import { SourceDialog } from "@/components/logs/source-dialog";
import { useFiltered } from "@/components/logs/use-filtered";
import { AllowlistDialog } from "@/components/settings/allowlist-dialog";
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
export function LogViewer({ state, onChange, servers, serverId, extra }: {
  state: ViewState;
  onChange: (next: ViewState) => void;
  servers: Server[];
  /** The one server the source dialog adds for, as on a server's Logs tab. */
  serverId?: string;
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
  // Each server's last list of containers; null when the read failed.
  const [listings] = useState(() => new Map<string, Promise<Container[] | null>>());
  const snapshot = useSyncExternalStore(subscribe, read, read);
  const [adding, setAdding] = useState(false);
  // Whether the person manages each group's log file patterns, read once per group for a file it refused.
  const [manages, setManages] = useState<ReadonlyMap<string, boolean>>(new Map());
  const [asked] = useState(() => new Set<string>());
  const [managing, setManaging] = useState<{ id: string; name: string } | null>(null);

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

  // Runs when the sources change, not on every new array of the same sources (a settings change).
  const sourcesKey = state.sources.map(encodeSource).join(" ");
  useEffect(() => {
    const sources = latest.current.state.sources;
    const wanted = new Map<string, string[]>();
    for (const s of sources) {
      if (s.kind === "container") wanted.set(s.server_id, [...(wanted.get(s.server_id) ?? []), s.container_id]);
    }
    if (wanted.size === 0) {
      store.setSources(sources);
      return;
    }
    let current = true;
    // A list read earlier is used while it holds every container asked for. A failed read, or one without an ID
    // asked for now, is read again: an old list could swap a container created since back to the one it replaced.
    const containersOf = async (id: string, ids: string[]) => {
      let list = await listings.get(id);
      if (!list || ids.some((c) => !list!.some((listed) => listed.container_id === c))) {
        const listing = apiFetch<Container[]>(`/servers/${id}/containers`).catch(() => null);
        listings.set(id, listing);
        list = await listing;
      }
      return [id, list] as const;
    };
    // Every source waits for the lists, journals and files too: one subscribe then carries the sources in their
    // order, with any swapped container, and the reads take a moment.
    void Promise.all([...wanted].map(([id, ids]) => containersOf(id, ids))).then((pairs) => {
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
  }, [sourcesKey, store, listings]);

  const { settings } = state;
  const merged = settings.layout === "merged";
  const { entries } = snapshot;
  const byId = useMemo(() => new Map(servers.map((s) => [s.id, s])), [servers]);
  const serverName = (id: string) => byId.get(id)?.name ?? UNKNOWN_SERVER;
  const groupOf = (id: string) => byId.get(id);

  // The groups of the files refused for matching none of their patterns.
  const refusedGroups = [...new Set(entries.flatMap((e) => {
    const group = e.state.state === "denied" && e.state.reason === "not_allowed" && groupOf(e.source.server_id);
    return group ? [group.group_id] : [];
  }))].join(" ");
  useEffect(() => {
    for (const group of refusedGroups ? refusedGroups.split(" ") : []) {
      if (asked.has(group)) continue;
      asked.add(group);
      apiFetch<{ can_manage: boolean }>(`/server-groups/${group}/log-allowlist`).then(
        (list) => setManages((known) => new Map(known).set(group, list.can_manage)),
        () => asked.delete(group),
      );
    }
  }, [refusedGroups, asked]);
  const serverOf = (sourceId: string) => {
    const entry = entries.find((e) => e.id === sourceId);
    return entry && groupOf(entry.source.server_id);
  };
  const managesPatterns = (sourceId: string) => {
    const server = serverOf(sourceId);
    return server !== undefined && manages.get(server.group_id) === true;
  };
  const managePatterns = (sourceId: string) => {
    const server = serverOf(sourceId);
    if (server) setManaging({ id: server.group_id, name: server.group_name });
  };
  // A merged pane's label and coloured tag of each source: its server and what it follows.
  const tagged = useMemo(() => {
    const labels = new Map<string, string>();
    const tags = new Map<string, { text: string; tone: number }>();
    entries.forEach((e, i) => {
      const text = `${byId.get(e.source.server_id)?.name ?? UNKNOWN_SERVER} · ${sourceLabel(e.source)}`;
      labels.set(e.id, text);
      tags.set(e.id, { text, tone: i % TONES });
    });
    return { labels, tags };
  }, [entries, byId]);
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
        matched={filtered.matched} total={filtered.total} onAddSource={() => setAdding(true)} extra={extra} />
      {snapshot.idle && (
        <div className="flex flex-wrap items-center gap-2 rounded-md border px-3 py-2 text-sm">
          <p className="min-w-0 flex-1">Paused after 30 minutes without activity.</p>
          <Button size="sm" variant="outline" onClick={() => store.resume()}>Resume</Button>
        </div>
      )}
      {merged ? (
        // No remove button: a merged pane has no one source to remove. Side by side, each pane has its own.
        entries.length > 0 && (
          <LogPane {...pane} title="Merged" entry={null} entries={entries} rows={filtered.lists[0] ?? []}
            merged={tagged} onManagePatterns={managePatterns} managesPatterns={managesPatterns}
            downloadParts={["merged"]} />
        )
      ) : (
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {entries.map((entry, i) => {
            const title = serverName(entry.source.server_id);
            return (
              <LogPane key={entry.id} {...pane} title={title} entry={entry} entries={[entry]}
                rows={filtered.lists[i] ?? []} merged={null} onRemove={remove}
                onManagePatterns={managesPatterns(entry.id) ? managePatterns : undefined}
                downloadParts={[title, sourceLabel(entry.source)]} />
            );
          })}
        </div>
      )}
      <SourceDialog open={adding} onOpenChange={setAdding} servers={servers} serverId={serverId}
        current={state.sources} onAdd={(added) => onChange({ ...state, sources: [...state.sources, ...added] })} />
      <AllowlistDialog group={managing} open={managing !== null} onOpenChange={(open) => !open && setManaging(null)} />
    </div>
  );
}
