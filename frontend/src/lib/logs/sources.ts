import type { Container } from "@/lib/checks";
import { LEVEL_GROUPS, type LevelGroup } from "@/lib/logs/levels";

export const PRIORITIES = ["emerg", "alert", "crit", "err", "warning", "notice", "info", "debug"] as const;
export type Priority = (typeof PRIORITIES)[number];

export type JournalSource = {
  kind: "journal";
  server_id: string;
  unit: string | null;
  priority: Priority | null;
  this_boot: boolean;
};
export type FileSource = { kind: "file"; server_id: string; path: string };
/** `name` is the container's name when it was added, kept to find it again once it is recreated with a new ID. */
export type ContainerSource = { kind: "container"; server_id: string; container_id: string; name: string | null };
export type LogSource = JournalSource | FileSource | ContainerSource;

export type ViewSettings = {
  q: string;
  regex: boolean;
  levels: LevelGroup[];
  layout: "side_by_side" | "merged";
  wrap: boolean;
  utc: boolean;
};
export type ViewState = { sources: LogSource[]; settings: ViewSettings };

export const DEFAULT_SETTINGS: ViewSettings = {
  q: "",
  regex: false,
  levels: [...LEVEL_GROUPS],
  layout: "side_by_side",
  wrap: false,
  utc: false,
};
export const MAX_SOURCES = 16;
export const MAX_PER_SERVER = 8;
export const MAX_FILTER = 200;

// The rules of backend/app/logs/sources.py. None of them allows "~", which joins the fields in the address.
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const UNIT = /^[A-Za-z0-9][A-Za-z0-9:_.@-]{0,254}$/;
const PATH = /^\/[A-Za-z0-9._/@%+=:,-]{0,254}$/;
const CONTAINER = /^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$/;
const SEPARATOR = "~";
const KINDS = { j: "journal", f: "file", c: "container" } as const;
const LETTERS = { journal: "j", file: "f", container: "c" } as const;

export function checkUnit(value: string): boolean {
  return UNIT.test(value);
}

/** Absolute, of allowed characters, and every segment non-empty and not "." or "..". */
export function checkPath(value: string): boolean {
  return PATH.test(value) && value.slice(1).split("/").every((part) => part !== "" && part !== "." && part !== "..");
}

export function checkContainer(value: string): boolean {
  return CONTAINER.test(value);
}

function isPriority(value: string): value is Priority {
  return (PRIORITIES as readonly string[]).includes(value);
}

/** The source in the address, which is also its local id: its fields joined with "~", trailing empty ones left out. */
export function encodeSource(s: LogSource): string {
  let fields: string[];
  switch (s.kind) {
    case "journal":
      fields = [s.unit ?? "", s.priority ?? "", s.this_boot ? "1" : ""];
      break;
    case "file":
      fields = [s.path];
      break;
    case "container":
      fields = [s.container_id, s.name ?? ""];
      break;
  }
  while (fields.length > 0 && fields[fields.length - 1] === "") fields.pop();
  return [LETTERS[s.kind], s.server_id, ...fields].join(SEPARATOR);
}

/** The source an address entry names, or null when it breaks a rule. */
export function decodeSource(text: string): LogSource | null {
  const [letter, serverId, ...rest] = text.split(SEPARATOR);
  const kind = KINDS[letter as keyof typeof KINDS];
  if (kind === undefined || serverId === undefined || !UUID.test(serverId)) return null;
  const server_id = serverId.toLowerCase();
  switch (kind) {
    case "journal": {
      if (rest.length > 3) return null;
      const [unit = "", priority = "", boot = ""] = rest;
      if ((unit !== "" && !checkUnit(unit)) || (priority !== "" && !isPriority(priority))) return null;
      if (boot !== "" && boot !== "1") return null;
      return { kind, server_id, unit: unit || null, priority: (priority as Priority) || null, this_boot: boot === "1" };
    }
    case "file": {
      if (rest.length !== 1 || !checkPath(rest[0])) return null;
      return { kind, server_id, path: rest[0] };
    }
    case "container": {
      if (rest.length < 1 || rest.length > 2) return null;
      const [container_id, name = ""] = rest;
      if (!checkContainer(container_id) || (name !== "" && !checkContainer(name))) return null;
      return { kind, server_id, container_id, name: name || null };
    }
  }
}

/** The view an address holds, and the saved view it came from. */
export function stateFrom(params: URLSearchParams): ViewState & { view: string | null } {
  const sources: LogSource[] = [];
  const seen = new Set<string>();
  for (const text of params.getAll("src")) {
    if (sources.length === MAX_SOURCES) break;
    const source = decodeSource(text);
    if (source === null) continue;
    const id = encodeSource(source);
    if (seen.has(id)) continue;
    seen.add(id);
    sources.push(source);
  }
  const lv = params.get("lv");
  const words = lv === null ? null : new Set(lv.split(","));
  const settings: ViewSettings = {
    q: (params.get("q") ?? "").slice(0, MAX_FILTER),
    regex: params.get("re") === "1",
    levels: words === null ? [...LEVEL_GROUPS] : LEVEL_GROUPS.filter((level) => words.has(level)),
    layout: params.get("layout") === "merged" ? "merged" : "side_by_side",
    wrap: params.get("wrap") === "1",
    utc: params.get("tz") === "utc",
  };
  return { sources, settings, view: params.get("view") || null };
}

/** The address of a view, without a leading "?": every default is left out, so the default view is "". */
export function queryOf(state: ViewState, view?: string | null): string {
  const { settings } = state;
  const params = new URLSearchParams();
  for (const source of state.sources) params.append("src", encodeSource(source));
  if (settings.q !== "") params.set("q", settings.q);
  if (settings.regex) params.set("re", "1");
  const levels = LEVEL_GROUPS.filter((level) => settings.levels.includes(level));
  if (levels.length !== LEVEL_GROUPS.length) params.set("lv", levels.join(","));
  if (settings.layout === "merged") params.set("layout", "merged");
  if (settings.wrap) params.set("wrap", "1");
  if (settings.utc) params.set("tz", "utc");
  if (view) params.set("view", view);
  return params.toString();
}

/** The source as `subscribe` sends it: a container goes without its name. */
export function wire(s: LogSource): Record<string, unknown> {
  if (s.kind === "container") return { kind: s.kind, server_id: s.server_id, container_id: s.container_id };
  return { ...s };
}

/** Whether the socket's description of a source (every field it knows, defaults included) is this source. */
export function sameSource(s: LogSource, described: Record<string, unknown>): boolean {
  const fields = wire(s);
  const keys = Object.keys(fields);
  return keys.length === Object.keys(described).length && keys.every((key) => described[key] === fields[key]);
}

export function sourceLabel(s: LogSource): string {
  switch (s.kind) {
    case "journal": {
      const parts = ["Journal"];
      if (s.unit !== null) parts.push(s.unit);
      if (s.priority !== null) parts.push(`${s.priority} and worse`);
      if (s.this_boot) parts.push("this boot");
      return parts.join(" · ");
    }
    case "file":
      return `File · ${s.path}`;
    case "container":
      return `Container · ${s.name ?? s.container_id.slice(0, 12)}`;
  }
}

/**
 * The sources with each recreated container found again: a container whose ID its server no longer lists takes the
 * ID of the one listed container with its name. The same array comes back when nothing changed.
 */
export function swapContainers(
  sources: LogSource[],
  containers: Map<string, Container[]>,
): { sources: LogSource[]; changed: boolean } {
  let changed = false;
  const next = sources.map((s) => {
    if (s.kind !== "container" || s.name === null) return s;
    const listed = containers.get(s.server_id);
    if (listed === undefined || listed.some((c) => c.container_id === s.container_id)) return s;
    const named = listed.filter((c) => c.name === s.name);
    if (named.length !== 1) return s;
    changed = true;
    return { ...s, container_id: named[0].container_id };
  });
  return changed ? { sources: next, changed } : { sources, changed };
}

const text = (value: unknown): value is string => typeof value === "string";
const optional = (value: unknown): value is string | null | undefined => value == null || text(value);

/** A source of a saved view as the API gives it, or null when it breaks a rule. Missing optional fields default. */
export function normalizeSource(raw: Record<string, unknown>): LogSource | null {
  const { kind, server_id } = raw;
  if (!text(server_id) || !UUID.test(server_id)) return null;
  const id = server_id.toLowerCase();
  switch (kind) {
    case "journal": {
      const { unit, priority, this_boot } = raw;
      if (!optional(unit) || !optional(priority) || (this_boot != null && typeof this_boot !== "boolean")) return null;
      if ((unit != null && !checkUnit(unit)) || (priority != null && !isPriority(priority))) return null;
      return { kind, server_id: id, unit: unit ?? null, priority: priority ?? null, this_boot: this_boot ?? false };
    }
    case "file": {
      const { path } = raw;
      if (!text(path) || !checkPath(path)) return null;
      return { kind, server_id: id, path };
    }
    case "container": {
      const { container_id, name } = raw;
      if (!text(container_id) || !checkContainer(container_id) || !optional(name)) return null;
      if (name != null && !checkContainer(name)) return null;
      return { kind, server_id: id, container_id, name: name ?? null };
    }
    default:
      return null;
  }
}
