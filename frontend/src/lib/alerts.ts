import { type ServerFilters, withQuery } from "@/lib/servers";

export type Severity = "warning" | "critical";
export type AlertMetric =
  | "cpu.used_percent"
  | "mem.used_percent"
  | "disk.used_percent"
  | "disk.inodes_used_percent"
  | "load.1m"
  | "load.5m"
  | "load.15m"
  | "unreachable";
export type Comparison = "above" | "below";
export type AlertState = "firing" | "resolved" | "ended";
export type EndReason = "rule_changed" | "rule_disabled" | "rule_deleted" | "server_not_monitored";
export type AlertEventKind = "fired" | "resolved" | "ended";

/** One alert of GET /api/alerts. The rule fields are the alert's copy of its rule; `rule_id` is null once it is gone. */
export type Alert = {
  id: string;
  server_id: string;
  server_name: string;
  group_id: string;
  group_name: string;
  rule_id: string | null;
  rule_name: string;
  metric: AlertMetric;
  comparison: Comparison | null;
  threshold: number | null;
  duration_seconds: number;
  severity: Severity;
  instance: string;
  state: AlertState;
  end_reason: EndReason | null;
  fired_at: string;
  resolved_at: string | null;
  value: number | null;
  last_value: number | null;
  peak_value: number | null;
};
export type AlertEvent = { id: string; kind: AlertEventKind; at: string; alert: Alert };
/** GET /api/alerts/events: the unseen count, the firing count and the 10 latest events. */
export type AlertEvents = { unseen: number; firing: number; events: AlertEvent[] };

export type AlertRule = {
  id: string;
  name: string;
  metric: AlertMetric;
  comparison: Comparison | null;
  threshold: number | null;
  duration_seconds: number;
  severity: Severity;
  server_group_id: string | null;
  server_group_name: string | null;
  server_id: string | null;
  server_name: string | null;
  enabled: boolean;
  revision: number;
  suggested_playbook_id: string | null;
  firing_count: number;
  created_at: string;
  updated_at: string;
};
/** The body of POST /api/alert-rules. */
export type AlertRuleInput = {
  name: string;
  metric: AlertMetric;
  comparison: Comparison | null;
  threshold: number | null;
  duration_seconds: number;
  severity: Severity;
  server_group_id: string | null;
  server_id: string | null;
  enabled: boolean;
};

/** The last delivery: `at` is when it was delivered, when it is tried next, or when it was last tried. */
export type Delivery = { state: "pending" | "delivered" | "failed"; at: string; error: string | null };
export type EmailSettings = {
  enabled: boolean;
  host: string | null;
  port: number;
  security: "starttls" | "tls" | "none";
  username: string | null;
  password_set: boolean;
  from_name: string;
  from_address: string | null;
  extra_addresses: string[];
  min_severity: Severity;
  last_delivery: Delivery | null;
};
export type ChannelKind = "webhook_json" | "webhook_slack" | "telegram";
export type Channel = {
  id: string;
  name: string;
  kind: ChannelKind;
  min_severity: Severity;
  enabled: boolean;
  hint: string;
  created_at: string;
  updated_at: string;
  last_delivery: Delivery | null;
};

export type MetricSpec = { label: string; unit: "%" | "per core" | null; max: number | null; perInstance: boolean };

/** The backend's catalog (app/alerts/catalog.py). */
export const METRICS: Record<AlertMetric, MetricSpec> = {
  "cpu.used_percent": { label: "CPU used", unit: "%", max: 100, perInstance: false },
  "mem.used_percent": { label: "Memory used", unit: "%", max: 100, perInstance: false },
  "disk.used_percent": { label: "Space used", unit: "%", max: 100, perInstance: true },
  "disk.inodes_used_percent": { label: "Inodes used", unit: "%", max: 100, perInstance: true },
  "load.1m": { label: "Load per core (1 min)", unit: "per core", max: 1000, perInstance: false },
  "load.5m": { label: "Load per core (5 min)", unit: "per core", max: 1000, perInstance: false },
  "load.15m": { label: "Load per core (15 min)", unit: "per core", max: 1000, perInstance: false },
  unreachable: { label: "Unreachable", unit: null, max: null, perInstance: false },
};

export const SEVERITY_LABEL: Record<Severity, string> = { warning: "Warning", critical: "Critical" };

export const END_REASON_TEXT: Record<EndReason, string> = {
  rule_changed: "the rule was changed",
  rule_disabled: "the rule was switched off",
  rule_deleted: "the rule was deleted",
  server_not_monitored: "the server is no longer monitored",
};

const LOAD_WINDOW: Partial<Record<AlertMetric, string>> = { "load.1m": "1 min", "load.5m": "5 min", "load.15m": "15 min" };

// The sentences below say exactly what app/notify/messages.py says.

/** "" for 0, "2 h", "1 h 30 min", or "10 min" (at least 1 min). */
export function durationText(seconds: number): string {
  if (seconds === 0) return "";
  const hours = Math.floor(seconds / 3600);
  const rest = seconds % 3600;
  if (hours > 0 && rest === 0) return `${hours} h`;
  if (hours > 0) return `${hours} h ${Math.floor(rest / 60)} min`;
  return `${Math.max(Math.floor(seconds / 60), 1)} min`;
}

type Condition = Pick<AlertRule, "metric" | "comparison" | "threshold" | "duration_seconds">;

/** "Space used above 90% for 10 min", or "Unreachable for 5 min". */
export function ruleSentence({ metric, comparison, threshold, duration_seconds }: Condition): string {
  const duration = duration_seconds === 0 ? "" : ` for ${durationText(duration_seconds)}`;
  if (metric === "unreachable") return `Unreachable${duration}`;
  const spec = METRICS[metric];
  const unit = spec.unit === "%" ? "%" : " per core";
  return `${spec.label} ${comparison} ${String(threshold)}${unit}${duration}`;
}

/** "93.3%" for percentages, "1.50 per core" for load. */
export function valueText(metric: AlertMetric, value: number): string {
  return METRICS[metric].unit === "%" ? `${value.toFixed(1)}%` : `${value.toFixed(2)} per core`;
}

/**
 * What the alert says happened: with the fired value, or with the last value when it tells a resolve (by default,
 * when the alert has resolved).
 */
export function alertHeadline(
  alert: Alert,
  kind: AlertEventKind = alert.state === "resolved" ? "resolved" : "fired",
): string {
  const { server_name: server, metric, instance } = alert;
  if (metric === "unreachable") return `${server} is unreachable`;
  const value = valueText(metric, (kind === "resolved" ? alert.last_value : alert.value) ?? 0);
  switch (metric) {
    case "cpu.used_percent":
      return `${server}: CPU is ${value} busy`;
    case "mem.used_percent":
      return `${server}: memory is ${value} used`;
    case "disk.used_percent":
      return `${server}: ${instance} is ${value} full`;
    case "disk.inodes_used_percent":
      return `${server}: ${instance} has ${value} of its inodes used`;
    default:
      return `${server}: load is ${value} (${LOAD_WINDOW[metric]})`;
  }
}

/** The sentence of one event, as the bell and the messages tell it. */
export function eventSentence(event: AlertEvent): string {
  const { alert } = event;
  if (event.kind === "ended") {
    const reason = alert.end_reason === null ? "" : END_REASON_TEXT[alert.end_reason];
    return `Ended: ${alert.server_name}: ${alert.rule_name}, ${reason}`;
  }
  if (event.kind === "resolved") {
    if (alert.metric === "unreachable") return `Resolved: ${alert.server_name} is reachable again`;
    return `Resolved: ${alertHeadline(alert, "resolved")}`;
  }
  return alertHeadline(alert, "fired");
}

/** The API path listing the firing or the closed alerts of the servers matching these filters, older than `before`. */
export function alertsPath(state: "firing" | "closed", filters: ServerFilters, before?: string): string {
  const extra: Record<string, string> = { state };
  if (before !== undefined) extra.before = before;
  return withQuery("/alerts", "group_id", filters, extra);
}

/** How many alerts are firing on each server that has any. */
export function firingByServer(alerts: Alert[]): Record<string, number> {
  const counts: Record<string, number> = {};
  for (const alert of alerts) {
    if (alert.state === "firing") counts[alert.server_id] = (counts[alert.server_id] ?? 0) + 1;
  }
  return counts;
}
