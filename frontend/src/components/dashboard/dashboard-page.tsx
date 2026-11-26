"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { FleetSummary } from "@/components/dashboard/fleet-summary";
import { ServerCard } from "@/components/dashboard/server-card";
import { ServerRows } from "@/components/dashboard/server-rows";
import { ViewSwitch, type DashboardView } from "@/components/dashboard/view-switch";
import { LiveBadge } from "@/components/metrics/live-badge";
import { ServerFilters } from "@/components/servers/server-filters";
import { Alert } from "@/components/ui/alert";
import { Card, CardAction, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { useLiveMetrics } from "@/hooks/use-live-metrics";
import { useOnScreen } from "@/hooks/use-on-screen";
import { useRefresh } from "@/hooks/use-refresh";
import type { ServerGroup } from "@/lib/access";
import { ApiError, apiFetch } from "@/lib/api";
import { messageFor } from "@/lib/auth/messages";
import {
  applyMessage,
  fleetOrder,
  mergeOverview,
  pushTrend,
  TREND_STEP_MS,
  vitalsOf,
  type LiveMessage,
  type OverviewRead,
  type ServerOverviewRead,
  type Vitals,
} from "@/lib/metrics";
import { addressOf, filtersFrom, listPath, type Server, type ServerFilters as Filters } from "@/lib/servers";

type Lists = { groups: ServerGroup[]; tags: string[]; servers: Server[] };

/** Cards turn to dashes when their newest values grow stale, so the page looks at the clock this often. */
const TICK_MS = 5_000;

/**
 * The vitals of an overview read, unless the page already holds newer live values: those then win, and the read
 * only fills what they lack (older trend slots, values the live message had not).
 */
function readInto(previous: Vitals | undefined, read: ServerOverviewRead): Vitals {
  const fresh = vitalsOf(read);
  const before = previous?.overview.time ? Date.parse(previous.overview.time) : null;
  const after = fresh.overview.time ? Date.parse(fresh.overview.time) : null;
  if (previous === undefined || before === null || (after !== null && after >= before)) {
    return { overview: mergeOverview(previous?.overview ?? null, fresh.overview), trend: fresh.trend };
  }
  const { start, cpu, mem } = previous.trend;
  const trend = cpu.reduce(
    (t, value, i) => pushTrend(t, start + i * TREND_STEP_MS, value, mem[i]),
    fresh.trend,
  );
  return { overview: mergeOverview(fresh.overview, previous.overview), trend };
}

/** The Dashboard: every server the person sees, filtered like the Servers page, updated live for those on screen. */
export function DashboardPage() {
  const router = useRouter();
  const params = useSearchParams();
  const filters = filtersFrom(params);
  const view: DashboardView = params.get("view") === "table" ? "table" : "cards";
  const path = listPath(filters);
  const [lists, setLists] = useState<Lists | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [vitals, setVitals] = useState<Record<string, Vitals>>({});
  const [now, setNow] = useState(() => Date.now());
  // Each foreground read takes a number; an answer is applied only while its read is still the latest.
  const reads = useRef(0);
  // The servers whose overview has been asked for once already, so coming on screen asks only once.
  const asked = useRef(new Set<string>());

  const reload = useCallback(() => {
    const read = ++reads.current;
    return Promise.all([
      apiFetch<ServerGroup[]>("/server-groups"),
      apiFetch<string[]>("/server-tags"),
      apiFetch<Server[]>(path),
    ]).then(
      ([groups, tags, servers]) => {
        if (read !== reads.current) return;
        setLists({ groups, tags, servers });
        setError(null);
      },
      (e: unknown) => {
        if (read === reads.current) setError(e instanceof ApiError ? e.detail : "error");
      },
    );
  }, [path]);

  useEffect(() => {
    void reload();
  }, [reload]);

  const readOverview = useCallback((ids: string[], background: boolean) => {
    if (ids.length === 0) return;
    for (const id of ids) asked.current.add(id);
    const query = ids.map((id) => "server_id=" + encodeURIComponent(id)).join("&");
    apiFetch<OverviewRead>("/metrics/overview?" + query, { background }).then(
      (read) =>
        setVitals((current) => {
          const next = { ...current };
          for (const server of read.servers) next[server.server_id] = readInto(current[server.server_id], server);
          return next;
        }),
      () => {},
    );
  }, []);

  const servers = useMemo(() => fleetOrder(lists?.servers ?? []), [lists]);
  const { track, onScreen } = useOnScreen();
  const live = useMemo(() => {
    const linux = new Set(servers.filter((s) => s.os === "linux").map((s) => s.id));
    return onScreen.filter((id) => linux.has(id));
  }, [servers, onScreen]);

  useEffect(() => {
    readOverview(
      live.filter((id) => !asked.current.has(id)),
      false,
    );
  }, [live, readOverview]);

  // A background re-read replaces the servers only if no foreground read started meanwhile, and fails silently.
  const refresh = useCallback(() => {
    const read = reads.current;
    apiFetch<Server[]>(path, { background: true }).then(
      (next) => {
        if (reads.current === read) setLists((l) => l && { ...l, servers: next });
      },
      () => {},
    );
    readOverview(live, true);
  }, [path, live, readOverview]);
  useRefresh(refresh, true);

  const onMessage = useCallback((m: LiveMessage) => {
    if (m.type === "overview") setVitals((v) => ({ ...v, [m.server_id]: applyMessage(v[m.server_id], m) }));
  }, []);
  const onOpen = useCallback(() => readOverview(live, true), [live, readOverview]);
  const status = useLiveMetrics({ view: "overview", serverIds: live, onMessage, onOpen });

  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), TICK_MS);
    return () => clearInterval(timer);
  }, []);

  // ServerRows hands every row to this one ref; each row carries its server's id, and the cleanup lets it go.
  const trackRow = useCallback(
    (element: Element | null) => {
      const id = element?.getAttribute("data-server-id");
      if (!id) return;
      const ref = track(id);
      ref(element);
      return () => ref(null);
    },
    [track],
  );

  const extra = (next: DashboardView): Record<string, string> => (next === "table" ? { view: "table" } : {});
  const filtered = filters.group !== null || filters.tags.length > 0;

  return (
    <div className="space-y-6">
      {error && <Alert variant="destructive">{messageFor(error)}</Alert>}
      <Card>
        <CardHeader>
          <CardTitle>
            <h2>Dashboard</h2>
          </CardTitle>
          <CardAction>
            <LiveBadge status={status} />
          </CardAction>
        </CardHeader>
        {lists && (
          <CardContent className="space-y-4">
            {lists.groups.length === 0 ? (
              <p className="text-muted-foreground">
                You do not see any server group yet. Ask the Owner of this installation for a role.
              </p>
            ) : (
              <>
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <ServerFilters
                    groups={lists.groups}
                    tags={lists.tags}
                    filters={filters}
                    onChange={(next: Filters) => router.replace(addressOf("/", next, extra(view)))}
                  />
                  <ViewSwitch view={view} onChange={(next) => router.replace(addressOf("/", filters, extra(next)))} />
                </div>
                <FleetSummary servers={lists.servers} />
                {servers.length === 0 && <Empty filtered={filtered} />}
              </>
            )}
          </CardContent>
        )}
      </Card>
      {/* The firing alerts go here with MITA-29. */}
      {servers.length > 0 &&
        (view === "table" ? (
          <Card>
            <CardContent>
              <ServerRows servers={servers} vitalsOf={vitals} now={now} track={trackRow} />
            </CardContent>
          </Card>
        ) : (
          <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
            {servers.map((server) => (
              <ServerCard key={server.id} server={server} vitals={vitals[server.id]} now={now} track={track(server.id)} />
            ))}
          </div>
        ))}
    </div>
  );
}

function Empty({ filtered }: { filtered: boolean }) {
  if (filtered) return <p className="text-muted-foreground">No servers match these filters.</p>;
  return (
    <div className="space-y-1">
      <p className="font-medium">No servers yet.</p>
      <p className="text-muted-foreground">
        Servers are registered on the{" "}
        <Link href="/servers" className="underline">
          Servers page
        </Link>
        .
      </p>
    </div>
  );
}
