import { emptyTrend, type Vitals } from "@/lib/metrics";
import type { MonitoringState, Server } from "@/lib/servers";

export const NOW = Date.parse("2026-11-26T12:00:00Z");

/** A Linux server in the group "Production"; `state` null when the collector has not looked at it yet. */
export function server(
  name: string,
  state: MonitoringState | null,
  { reason = null, ...extra }: Partial<Server> & { reason?: string | null } = {},
): Server {
  return {
    id: `id-${name}`,
    name,
    address: "10.0.0.1",
    port: 22,
    os: "linux",
    role: null,
    tags: [],
    group_id: "g",
    group_name: "Production",
    connection_settings: { username: "megoo" },
    host_key: null,
    created_at: "2026-11-26T11:00:00Z",
    updated_at: "2026-11-26T11:00:00Z",
    can_manage: false,
    host_key_state: "pinned",
    host_key_fingerprint: null,
    host_key_type: null,
    host_key_pinned_at: null,
    host_key_changed_at: null,
    host_key_offered: null,
    can_connect: true,
    can_view_logs: false,
    metrics_interval_seconds: 5,
    monitoring: state === null ? null : { state, reason, since: "2026-11-26T11:00:00Z", last_sample_at: null },
    ...extra,
  };
}

/** The newest numbers of a server, taken `ageMs` before NOW. */
export function vitals(serverId: string, ageMs = 5_000): Vitals {
  const time = NOW - ageMs;
  return {
    overview: {
      server_id: serverId,
      time: new Date(time).toISOString(),
      cpu: 42,
      mem: 61,
      load: 1.25,
      disk: { mount: "/var", percent: 73 },
      rx: 2048,
      tx: 1024,
    },
    trend: emptyTrend(time),
  };
}
