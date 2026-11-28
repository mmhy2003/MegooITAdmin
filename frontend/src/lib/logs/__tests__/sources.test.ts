import { describe, expect, it } from "vitest";
import type { Container } from "@/lib/checks";
import {
  checkContainer,
  checkPath,
  checkUnit,
  decodeSource,
  DEFAULT_SETTINGS,
  encodeSource,
  type LogSource,
  MAX_FILTER,
  MAX_PER_SERVER,
  MAX_SOURCES,
  normalizeSource,
  queryOf,
  sameSource,
  sourceLabel,
  stateFrom,
  swapContainers,
  type ViewState,
  wire,
} from "@/lib/logs/sources";

const S = "6f1c2d3e-4a5b-4c6d-8e7f-901234567890";
const T = "0a1b2c3d-4e5f-4a6b-9c7d-8e9f01234567";
const ID = "3f2a9b8c7d6e5f4a3b2c1d0e9f8a7b6c5d4e3f2a1b0c9d8e7f6a5b4c3d2e1f0a";

const journal = (fields: Partial<Extract<LogSource, { kind: "journal" }>> = {}): LogSource => ({
  kind: "journal",
  server_id: S,
  unit: null,
  priority: null,
  this_boot: false,
  ...fields,
});
const file = (path: string, server_id = S): LogSource => ({ kind: "file", server_id, path });
const container = (container_id: string, name: string | null = null, server_id = S): LogSource => ({
  kind: "container",
  server_id,
  container_id,
  name,
});

function listed(container_id: string, name: string): Container {
  return {
    container_id,
    runtime: "docker",
    name,
    image: "nginx:1.27",
    compose_project: null,
    compose_service: null,
    state: "running",
    status: "Up 2 hours",
    first_seen_at: "2026-11-28T09:00:00Z",
    last_seen_at: "2026-11-28T09:05:00Z",
  };
}

describe("the limits", () => {
  it("are those of the backend", () => {
    expect([MAX_SOURCES, MAX_PER_SERVER, MAX_FILTER]).toEqual([16, 8, 200]);
    expect(DEFAULT_SETTINGS).toEqual({
      q: "",
      regex: false,
      levels: ["error", "warning", "info", "debug", "none"],
      layout: "side_by_side",
      wrap: false,
      utc: false,
    });
  });
});

describe("the field rules", () => {
  it.each([
    ["nginx.service", true],
    ["user@1000.service", true],
    ["sys-fs-fuse-connections.mount", true],
    ["-option", false],
    ["", false],
    ["a b", false],
    ["a".repeat(255), true],
    ["a".repeat(256), false],
  ])("checkUnit(%j) is %s", (value, ok) => {
    expect(checkUnit(value)).toBe(ok);
  });

  it.each([
    ["/var/log/syslog", true],
    ["/var/log/nginx/access.log", true],
    ["/", false],
    ["relative", false],
    ["/a/../b", false],
    ["/a/./b", false],
    ["/a//b", false],
    ["/a/", false],
    ["/a b", false],
    ["/a~b", false],
    [`/${"a".repeat(254)}`, true],
    [`/${"a".repeat(255)}`, false],
  ])("checkPath(%j) is %s", (value, ok) => {
    expect(checkPath(value)).toBe(ok);
  });

  it.each([
    ["web", true],
    [ID, true],
    ["my_app.1-a", true],
    ["-web", false],
    ["", false],
    ["a/b", false],
    ["a".repeat(128), true],
    ["a".repeat(129), false],
  ])("checkContainer(%j) is %s", (value, ok) => {
    expect(checkContainer(value)).toBe(ok);
  });
});

describe("the address codec", () => {
  it.each<[string, LogSource]>([
    [`j~${S}`, journal()],
    [`j~${S}~nginx.service`, journal({ unit: "nginx.service" })],
    [`j~${S}~~warning`, journal({ priority: "warning" })],
    [`j~${S}~~~1`, journal({ this_boot: true })],
    [`j~${S}~unit~err~1`, journal({ unit: "unit", priority: "err", this_boot: true })],
    [`f~${S}~/var/log/syslog`, file("/var/log/syslog")],
    [`c~${S}~${ID}~web`, container(ID, "web")],
    [`c~${S}~${ID}`, container(ID)],
  ])("encodes and decodes %s", (text, source) => {
    expect(encodeSource(source)).toBe(text);
    expect(decodeSource(text)).toEqual(source);
  });

  it("pads trailing empty fields that are written", () => {
    expect(decodeSource(`j~${S}~~~`)).toEqual(journal());
    expect(decodeSource(`c~${S}~web~`)).toEqual(container("web"));
  });

  it("reads a server ID in capitals as the same server", () => {
    expect(decodeSource(`j~${S.toUpperCase()}`)).toEqual(journal());
  });

  it.each([
    ["a bad server ID", "j~not-a-uuid"],
    ["a missing server ID", "j"],
    ["a bad unit", `j~${S}~-u`],
    ["an unknown priority", `j~${S}~~verbose`],
    ["a bad boot field", `j~${S}~~~yes`],
    ["an extra journal field", `j~${S}~~~1~x`],
    ["a path with ..", `f~${S}~/a/../b`],
    ["a relative path", `f~${S}~relative`],
    ["a path with an empty segment", `f~${S}~/a//b`],
    ["a file without a path", `f~${S}`],
    ["an extra file field", `f~${S}~/var/log/syslog~x`],
    ["a bad container", `c~${S}~-web`],
    ["a container without an ID", `c~${S}`],
    ["a bad container name", `c~${S}~${ID}~a/b`],
    ["an extra container field", `c~${S}~${ID}~web~x`],
    ["an unknown kind", `x~${S}`],
    ["an empty text", ""],
  ])("refuses %s", (_, text) => {
    expect(decodeSource(text)).toBeNull();
  });
});

describe("stateFrom", () => {
  it("gives the defaults for an empty address", () => {
    expect(stateFrom(new URLSearchParams())).toEqual({ sources: [], settings: DEFAULT_SETTINGS, view: null });
  });

  it("drops invalid and duplicate sources and keeps the first 16", () => {
    const params = new URLSearchParams();
    params.append("src", `j~${S}`);
    params.append("src", "j~bad");
    params.append("src", `j~${S}~~~`);
    for (let i = 0; i < 20; i++) params.append("src", `f~${S}~/var/log/f${i}`);
    const { sources } = stateFrom(params);
    expect(sources).toHaveLength(16);
    expect(sources[0]).toEqual(journal());
    expect(sources[1]).toEqual(file("/var/log/f0"));
    expect(sources[15]).toEqual(file("/var/log/f14"));
  });

  it("cuts the filter at 200 characters and reads re=1", () => {
    const { settings } = stateFrom(new URLSearchParams({ q: "x".repeat(250), re: "1" }));
    expect(settings.q).toBe("x".repeat(200));
    expect(settings.regex).toBe(true);
    expect(stateFrom(new URLSearchParams({ re: "yes" })).settings.regex).toBe(false);
  });

  it("reads the levels: absent is all five, empty is none, unknown words are dropped", () => {
    expect(stateFrom(new URLSearchParams()).settings.levels).toEqual(DEFAULT_SETTINGS.levels);
    expect(stateFrom(new URLSearchParams("lv=")).settings.levels).toEqual([]);
    expect(stateFrom(new URLSearchParams("lv=info,fatal,error,info")).settings.levels).toEqual(["error", "info"]);
  });

  it("reads the layout, wrap, the time zone and the view", () => {
    const state = stateFrom(new URLSearchParams({ layout: "merged", wrap: "1", tz: "utc", view: "v1" }));
    expect(state.settings).toMatchObject({ layout: "merged", wrap: true, utc: true });
    expect(state.view).toBe("v1");
    const other = stateFrom(new URLSearchParams({ layout: "grid", wrap: "0", tz: "local", view: "" }));
    expect(other.settings).toMatchObject({ layout: "side_by_side", wrap: false, utc: false });
    expect(other.view).toBeNull();
  });
});

describe("queryOf", () => {
  const empty: ViewState = { sources: [], settings: DEFAULT_SETTINGS };

  it("is empty when everything is default", () => {
    expect(queryOf(empty)).toBe("");
    expect(queryOf(empty, null)).toBe("");
  });

  it("writes every parameter in order", () => {
    const state: ViewState = {
      sources: [journal({ unit: "nginx.service" }), container(ID, "web")],
      settings: { q: "a b", regex: true, levels: ["error", "warning"], layout: "merged", wrap: true, utc: true },
    };
    const params = new URLSearchParams(queryOf(state, "v1"));
    expect([...params.keys()]).toEqual(["src", "src", "q", "re", "lv", "layout", "wrap", "tz", "view"]);
    expect(params.getAll("src")).toEqual([`j~${S}~nginx.service`, `c~${S}~${ID}~web`]);
    expect(Object.fromEntries([...params].slice(2))).toEqual({
      q: "a b",
      re: "1",
      lv: "error,warning",
      layout: "merged",
      wrap: "1",
      tz: "utc",
      view: "v1",
    });
  });

  it("writes no level as lv=", () => {
    expect(queryOf({ sources: [], settings: { ...DEFAULT_SETTINGS, levels: [] } })).toBe("lv=");
  });

  it("round-trips through stateFrom", () => {
    const state: ViewState = {
      sources: [journal({ priority: "err", this_boot: true }), file("/var/log/syslog"), container(ID)],
      settings: { q: "x.*y", regex: true, levels: ["debug", "none"], layout: "merged", wrap: false, utc: true },
    };
    expect(stateFrom(new URLSearchParams(queryOf(state, "v2")))).toEqual({ ...state, view: "v2" });
    expect(stateFrom(new URLSearchParams(queryOf(empty)))).toEqual({ ...empty, view: null });
  });
});

describe("wire", () => {
  it("sends every field but a container's name", () => {
    expect(wire(container(ID, "web"))).toEqual({ kind: "container", server_id: S, container_id: ID });
    expect(wire(journal({ unit: "u" }))).toEqual(journal({ unit: "u" }));
    expect(wire(file("/var/log/syslog"))).toEqual(file("/var/log/syslog"));
  });
});

describe("sameSource", () => {
  it("matches the socket's description of each kind", () => {
    const j = journal({ unit: "nginx.service", priority: "warning" });
    expect(
      sameSource(j, { server_id: S, kind: "journal", unit: "nginx.service", priority: "warning", this_boot: false }),
    ).toBe(true);
    expect(sameSource(j, { server_id: S, kind: "journal", unit: "nginx.service", priority: null, this_boot: false })).toBe(
      false,
    );
    expect(sameSource(file("/var/log/syslog"), { server_id: S, kind: "file", path: "/var/log/syslog" })).toBe(true);
    expect(sameSource(file("/var/log/syslog"), { server_id: T, kind: "file", path: "/var/log/syslog" })).toBe(false);
    expect(sameSource(container(ID, "web"), { server_id: S, kind: "container", container_id: ID })).toBe(true);
    expect(sameSource(container(ID, "web"), { server_id: S, kind: "container", container_id: "other" })).toBe(false);
    expect(sameSource(container(ID), { server_id: S, kind: "file", path: "/var/log/syslog" })).toBe(false);
  });
});

describe("sourceLabel", () => {
  it.each<[LogSource, string]>([
    [journal(), "Journal"],
    [journal({ unit: "nginx.service" }), "Journal · nginx.service"],
    [
      journal({ unit: "nginx.service", priority: "warning", this_boot: true }),
      "Journal · nginx.service · warning and worse · this boot",
    ],
    [journal({ this_boot: true }), "Journal · this boot"],
    [file("/var/log/syslog"), "File · /var/log/syslog"],
    [container(ID, "web"), "Container · web"],
    [container(ID), `Container · ${ID.slice(0, 12)}`],
  ])("labels %j", (source, label) => {
    expect(sourceLabel(source)).toBe(label);
  });
});

describe("swapContainers", () => {
  const NEW = "9".repeat(64);

  it("swaps a container no longer listed for the one with its name", () => {
    const sources = [journal(), container(ID, "web")];
    const containers = new Map([[S, [listed(NEW, "web"), listed("1".repeat(64), "db")]]]);
    expect(swapContainers(sources, containers)).toEqual({ sources: [journal(), container(NEW, "web")], changed: true });
  });

  it.each<[string, LogSource, Map<string, Container[]>]>([
    ["no container has the name", container(ID, "web"), new Map([[S, [listed(NEW, "db")]]])],
    ["two have it", container(ID, "web"), new Map([[S, [listed(NEW, "web"), listed("1".repeat(64), "web")]]])],
    ["the server is not in the map", container(ID, "web"), new Map([[T, [listed(NEW, "web")]]])],
    ["the ID is still listed", container(ID, "web"), new Map([[S, [listed(ID, "old"), listed(NEW, "web")]]])],
    ["the source has no name", container(ID), new Map([[S, [listed(NEW, "web")]]])],
  ])("does not swap when %s", (_, source, containers) => {
    const sources = [source];
    const result = swapContainers(sources, containers);
    expect(result.changed).toBe(false);
    expect(result.sources).toBe(sources);
  });
});

describe("normalizeSource", () => {
  it("accepts the stored shapes", () => {
    const j = { kind: "journal", server_id: S, unit: "nginx.service", priority: "err", this_boot: true };
    expect(normalizeSource(j)).toEqual(j);
    expect(normalizeSource({ kind: "file", server_id: S, path: "/var/log/syslog" })).toEqual(file("/var/log/syslog"));
    expect(normalizeSource({ kind: "container", server_id: S, container_id: ID, name: "web" })).toEqual(
      container(ID, "web"),
    );
    expect(normalizeSource({ kind: "container", server_id: S, container_id: ID, name: null })).toEqual(container(ID));
  });

  it("gives the defaults of missing optional fields", () => {
    expect(normalizeSource({ kind: "journal", server_id: S })).toEqual(journal());
    expect(normalizeSource({ kind: "container", server_id: S, container_id: ID })).toEqual(container(ID));
  });

  it.each([
    ["an unknown kind", { kind: "x", server_id: S }],
    ["a bad server ID", { kind: "journal", server_id: "x" }],
    ["a bad unit", { kind: "journal", server_id: S, unit: "-u" }],
    ["an unknown priority", { kind: "journal", server_id: S, priority: "verbose" }],
    ["a boot field of another type", { kind: "journal", server_id: S, this_boot: "1" }],
    ["a bad path", { kind: "file", server_id: S, path: "/a/../b" }],
    ["a missing path", { kind: "file", server_id: S }],
    ["a bad container", { kind: "container", server_id: S, container_id: "-web" }],
    ["a bad name", { kind: "container", server_id: S, container_id: ID, name: "a b" }],
    ["a unit of another type", { kind: "journal", server_id: S, unit: 3 }],
  ])("refuses %s", (_, raw) => {
    expect(normalizeSource(raw)).toBeNull();
  });
});
