export type ServerOs = "linux" | "windows";
export const OS_LABELS: Record<ServerOs, string> = { linux: "Linux", windows: "Windows" };
export const DEFAULT_PORT: Record<ServerOs, number> = { linux: 22, windows: 3389 };
export const DEFAULT_USERNAME = "megoo";
export const DEFAULT_INTERVAL = 5;
export const MAX_TAGS = 20;
export type ConnectionSettings = { username: string };
export type HostKeyState = "none" | "not_pinned" | "pinned" | "changed";
/** The key a server presented when it no longer matched the pinned one. */
export type HostKeyOffer = { fingerprint: string; type: string; at: string };
export type MonitoringState = "reachable" | "unreachable" | "not_monitored";
export type MonitoringReason =
  | "unreachable"
  | "key_refused"
  | "ssh_error"
  | "no_samples"
  | "not_an_ssh_server"
  | "host_key_not_pinned"
  | "host_key_changed";
/** What the collector last wrote about a server. `reason` is a string: a newer backend may send one we do not know. */
export type Monitoring = { state: MonitoringState; reason: string | null; since: string; last_sample_at: string | null };
export type Server = {
  id: string;
  name: string;
  address: string;
  port: number;
  os: ServerOs;
  role: string | null;
  tags: string[];
  group_id: string;
  group_name: string;
  connection_settings: ConnectionSettings;
  host_key: string | null;
  created_at: string;
  updated_at: string;
  can_manage: boolean;
  host_key_state: HostKeyState;
  host_key_fingerprint: string | null;
  host_key_type: string | null;
  host_key_pinned_at: string | null;
  host_key_changed_at: string | null;
  host_key_offered: HostKeyOffer | null;
  can_connect: boolean;
  metrics_interval_seconds: number;
  monitoring: Monitoring | null;
};
export type ConnectionReason =
  | "unreachable"
  | "host_key_changed"
  | "key_refused"
  | "account_is_root"
  | "account_in_docker_group"
  | "account_not_in_log_groups"
  | "sudo_checker_missing"
  | "sudo_too_wide"
  | "account_check_failed"
  | "ssh_error";
export type CheckName =
  | "host_key"
  | "platform_key"
  | "not_root"
  | "not_in_docker_group"
  | "in_log_groups"
  | "sudo_checker"
  | "sudo_limited";
export type CheckStatus = "passed" | "failed" | "not_run";
export type ConnectionCheck = { name: CheckName; status: CheckStatus };
export type ConnectionTestResult = { ok: boolean; reason: ConnectionReason | null; checks: ConnectionCheck[] };
export type HostKeyFetchResult = {
  ok: boolean;
  reason: ConnectionReason | null;
  fingerprint: string | null;
  type: string | null;
};
export const CHECK_LABELS: Record<CheckName, string> = {
  host_key: "The host key matches the pinned key",
  platform_key: "The server accepts the platform's key",
  not_root: "The account is not root",
  not_in_docker_group: "The account is not in the docker group",
  in_log_groups: "The account is in systemd-journal and adm",
  sudo_checker: "megoo-ctl answers through sudo",
  sudo_limited: "sudo allows only megoo-ctl",
};
export const CHECK_STATUS_LABELS: Record<CheckStatus, string> = {
  passed: "Passed",
  failed: "Failed",
  not_run: "Not checked",
};
/** What the dialog edits; port is a number, role "" when none. */
export type ServerDraft = {
  name: string;
  address: string;
  group_id: string;
  os: ServerOs;
  port: number;
  interval: number;
  role: string;
  tags: string[];
  username: string;
};
/** The body of POST /api/servers. */
export type ServerBody = {
  name: string;
  address: string;
  group_id: string;
  os: ServerOs;
  port: number;
  metrics_interval_seconds: number;
  role: string | null;
  tags: string[];
  connection_settings: ConnectionSettings;
};
export type ServerFilters = { group: string | null; tags: string[] };

/** The command that prints the key's fingerprint on the server: ed25519, ecdsa or rsa. */
export function fingerprintCommand(type: string | null): string {
  let kind = "ed25519";
  if (type?.startsWith("ecdsa-")) kind = "ecdsa";
  else if (type === "ssh-rsa" || type?.startsWith("rsa-")) kind = "rsa";
  return `ssh-keygen -lf /etc/ssh/ssh_host_${kind}_key.pub`;
}

const TAG = /^[a-z0-9][a-z0-9._-]{0,31}$/;

/** The tag as the server stores it, or null when it is not a valid tag. */
export function cleanTag(raw: string): string | null {
  const tag = raw.trim().toLowerCase();
  return TAG.test(tag) ? tag : null;
}

/** The tags with one more; the same array when it is invalid, there already or one too many. */
export function addTag(tags: string[], raw: string): string[] {
  const tag = cleanTag(raw);
  if (tag === null || tags.includes(tag) || tags.length >= MAX_TAGS) return tags;
  return [...tags, tag];
}

/** What the dialog starts from: the server, or a new Linux server in the group. */
export function draftOf(server: Server | null, groupId: string): ServerDraft {
  if (server === null) {
    return {
      name: "",
      address: "",
      group_id: groupId,
      os: "linux",
      port: DEFAULT_PORT.linux,
      interval: DEFAULT_INTERVAL,
      role: "",
      tags: [],
      username: DEFAULT_USERNAME,
    };
  }
  return {
    name: server.name,
    address: server.address,
    group_id: server.group_id,
    os: server.os,
    port: server.port,
    interval: server.metrics_interval_seconds,
    role: server.role ?? "",
    tags: server.tags,
    username: server.connection_settings.username,
  };
}

/** The draft as the API takes it: trimmed, no empty role, tags sorted. */
export function bodyOf(draft: ServerDraft): ServerBody {
  const role = draft.role.trim();
  return {
    name: draft.name.trim(),
    address: draft.address.trim(),
    group_id: draft.group_id,
    os: draft.os,
    port: draft.port,
    metrics_interval_seconds: draft.interval,
    role: role === "" ? null : role,
    tags: [...draft.tags].sort(),
    connection_settings: { username: draft.username.trim() },
  };
}

/** The fields of the draft that differ from the server, for PATCH. */
export function changesOf(server: Server, draft: ServerDraft): Partial<ServerBody> {
  const body = bodyOf(draft);
  const changes: Partial<ServerBody> = {};
  if (body.name !== server.name) changes.name = body.name;
  if (body.address.toLowerCase() !== server.address.toLowerCase()) changes.address = body.address;
  if (body.group_id !== server.group_id) changes.group_id = body.group_id;
  if (body.os !== server.os) changes.os = body.os;
  if (body.port !== server.port) changes.port = body.port;
  if (body.metrics_interval_seconds !== server.metrics_interval_seconds) {
    changes.metrics_interval_seconds = body.metrics_interval_seconds;
  }
  if (body.role !== server.role) changes.role = body.role;
  if (body.tags.join(" ") !== [...server.tags].sort().join(" ")) changes.tags = body.tags;
  if (body.connection_settings.username !== server.connection_settings.username) {
    changes.connection_settings = body.connection_settings;
  }
  return changes;
}

/** The filters held in the address of the Servers page. */
export function filtersFrom(params: URLSearchParams): ServerFilters {
  const tags: string[] = [];
  for (const raw of params.getAll("tag")) {
    const tag = cleanTag(raw);
    if (tag !== null && !tags.includes(tag)) tags.push(tag);
  }
  return { group: params.get("group") || null, tags };
}

function withQuery(path: string, groupKey: string, filters: ServerFilters): string {
  const params = new URLSearchParams();
  if (filters.group !== null) params.set(groupKey, filters.group);
  for (const tag of filters.tags) params.append("tag", tag);
  const query = params.toString();
  return query === "" ? path : `${path}?${query}`;
}

/** The address of the Servers page showing these filters. */
export function addressOf(filters: ServerFilters): string {
  return withQuery("/servers", "group", filters);
}

/** The API path listing the servers that match these filters. */
export function listPath(filters: ServerFilters): string {
  return withQuery("/servers", "group_id", filters);
}
