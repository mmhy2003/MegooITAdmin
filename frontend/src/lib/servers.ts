export type ServerOs = "linux" | "windows";
export const OS_LABELS: Record<ServerOs, string> = { linux: "Linux", windows: "Windows" };
export const DEFAULT_PORT: Record<ServerOs, number> = { linux: 22, windows: 3389 };
export const DEFAULT_USERNAME = "megoo";
export const MAX_TAGS = 20;
export type ConnectionSettings = { username: string };
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
};
/** What the dialog edits; port is a number, role "" when none. */
export type ServerDraft = {
  name: string;
  address: string;
  group_id: string;
  os: ServerOs;
  port: number;
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
  role: string | null;
  tags: string[];
  connection_settings: ConnectionSettings;
};
export type ServerFilters = { group: string | null; tags: string[] };

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
