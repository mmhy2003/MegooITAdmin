import { describe, expect, it } from "vitest";
import {
  addressOf,
  addTag,
  bodyOf,
  CHECK_LABELS,
  changesOf,
  cleanTag,
  DEFAULT_INTERVAL,
  DEFAULT_PORT,
  draftOf,
  filtersFrom,
  fingerprintCommand,
  listPath,
  MAX_TAGS,
  type Server,
} from "@/lib/servers";

const SERVER: Server = {
  id: "s-1",
  name: "web-01",
  address: "web-01.example.com",
  port: 22,
  os: "linux",
  role: "web",
  tags: ["eu-west", "nginx"],
  group_id: "g-staging",
  group_name: "staging",
  connection_settings: { username: "megoo" },
  host_key: null,
  created_at: "2026-11-01T00:00:00Z",
  updated_at: "2026-11-01T00:00:00Z",
  can_manage: true,
  host_key_state: "not_pinned",
  host_key_fingerprint: null,
  host_key_type: null,
  host_key_pinned_at: null,
  host_key_changed_at: null,
  host_key_offered: null,
  can_connect: true,
  metrics_interval_seconds: 5,
  monitoring: null,
};

describe("DEFAULT_PORT", () => {
  it("is SSH for Linux and RDP for Windows", () => {
    expect(DEFAULT_PORT).toEqual({ linux: 22, windows: 3389 });
  });
});

describe("DEFAULT_INTERVAL", () => {
  it("starts the interval at DEFAULT_INTERVAL", () => {
    expect(DEFAULT_INTERVAL).toBe(5);
  });
});

describe("cleanTag", () => {
  it("trims and lowercases", () => {
    expect(cleanTag(" Web ")).toBe("web");
  });

  it.each(["", "-web", "a b", "web!", "x".repeat(33)])("refuses %j", (raw) => {
    expect(cleanTag(raw)).toBeNull();
  });
});

describe("addTag", () => {
  it("adds a cleaned tag", () => {
    expect(addTag(["db"], " Web")).toEqual(["db", "web"]);
  });

  it("ignores a duplicate and an invalid tag", () => {
    const tags = ["web"];
    expect(addTag(tags, "WEB")).toBe(tags);
    expect(addTag(tags, "a b")).toBe(tags);
  });

  it("ignores a tag past the limit", () => {
    const tags = Array.from({ length: MAX_TAGS }, (_, i) => `t${i}`);
    expect(addTag(tags, "one-more")).toBe(tags);
  });
});

describe("draftOf", () => {
  it("starts a new server as Linux on port 22 with the megoo account", () => {
    expect(draftOf(null, "g")).toEqual({
      name: "",
      address: "",
      group_id: "g",
      os: "linux",
      port: 22,
      interval: 5,
      role: "",
      tags: [],
      username: "megoo",
    });
  });

  it("copies a server, its missing role as empty", () => {
    expect(draftOf({ ...SERVER, role: null, metrics_interval_seconds: 3 }, "g")).toEqual({
      name: "web-01",
      address: "web-01.example.com",
      group_id: "g-staging",
      os: "linux",
      port: 22,
      interval: 3,
      role: "",
      tags: ["eu-west", "nginx"],
      username: "megoo",
    });
  });
});

describe("bodyOf", () => {
  it("trims, drops an empty role and sorts the tags", () => {
    expect(
      bodyOf({
        name: " web-01 ",
        address: " 10.0.0.1 ",
        group_id: "g",
        os: "windows",
        port: 3389,
        interval: 7,
        role: "  ",
        tags: ["web", "db"],
        username: " admin ",
      }),
    ).toEqual({
      name: "web-01",
      address: "10.0.0.1",
      group_id: "g",
      os: "windows",
      port: 3389,
      metrics_interval_seconds: 7,
      role: null,
      tags: ["db", "web"],
      connection_settings: { username: "admin" },
    });
  });

  it("keeps a role", () => {
    expect(bodyOf({ ...draftOf(null, "g"), role: " web " }).role).toBe("web");
  });
});

describe("changesOf", () => {
  it("is empty for an unchanged draft", () => {
    const draft = { ...draftOf(SERVER, "g"), tags: ["nginx", "eu-west"], address: "WEB-01.Example.com" };
    expect(changesOf(SERVER, draft)).toEqual({});
  });

  it("holds only the port after a port change", () => {
    expect(changesOf(SERVER, { ...draftOf(SERVER, "g"), port: 2222 })).toEqual({ port: 2222 });
  });

  it("holds only the interval after it changed", () => {
    expect(changesOf(SERVER, { ...draftOf(SERVER, "g"), interval: 10 })).toEqual({ metrics_interval_seconds: 10 });
  });

  it("holds the group after a move", () => {
    expect(changesOf(SERVER, { ...draftOf(SERVER, "g"), group_id: "g-production" })).toEqual({
      group_id: "g-production",
    });
  });

  it("holds a removed role, the tags and the account", () => {
    expect(changesOf(SERVER, { ...draftOf(SERVER, "g"), role: "", tags: ["db"], username: "root" })).toEqual({
      role: null,
      tags: ["db"],
      connection_settings: { username: "root" },
    });
  });
});

describe("filtersFrom", () => {
  it("reads the group and every tag, cleaned and once", () => {
    expect(filtersFrom(new URLSearchParams("group=g1&tag=Web&tag=web&tag=db"))).toEqual({
      group: "g1",
      tags: ["web", "db"],
    });
  });

  it("is empty without parameters, and drops an invalid tag", () => {
    expect(filtersFrom(new URLSearchParams("tag=a%20b"))).toEqual({ group: null, tags: [] });
  });
});

describe("addressOf", () => {
  it("is the bare page without filters", () => {
    expect(addressOf("/servers", { group: null, tags: [] })).toBe("/servers");
    expect(addressOf("/", { group: null, tags: [] })).toBe("/");
  });

  it("holds the group", () => {
    expect(addressOf("/servers", { group: "g1", tags: [] })).toBe("/servers?group=g1");
  });

  it("holds the group and every tag", () => {
    expect(addressOf("/servers", { group: "g1", tags: ["web", "db"] })).toBe("/servers?group=g1&tag=web&tag=db");
    expect(addressOf("/servers", { group: null, tags: ["web"] })).toBe("/servers?tag=web");
  });

  it("appends the other parameters after the group and the tags", () => {
    expect(addressOf("/", { group: "g", tags: ["web"] }, { view: "table" })).toBe("/?group=g&tag=web&view=table");
    expect(addressOf("/", { group: null, tags: [] }, { view: "table" })).toBe("/?view=table");
  });
});

describe("listPath", () => {
  it("is the bare list without filters", () => {
    expect(listPath({ group: null, tags: [] })).toBe("/servers");
  });

  it("asks for the group", () => {
    expect(listPath({ group: "g1", tags: [] })).toBe("/servers?group_id=g1");
  });

  it("asks for the group and every tag", () => {
    expect(listPath({ group: "g1", tags: ["web", "db"] })).toBe("/servers?group_id=g1&tag=web&tag=db");
    expect(listPath({ group: null, tags: ["web"] })).toBe("/servers?tag=web");
  });
});

describe("fingerprintCommand", () => {
  it.each([
    ["ssh-ed25519", "ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub"],
    [null, "ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub"],
    ["ecdsa-sha2-nistp256", "ssh-keygen -lf /etc/ssh/ssh_host_ecdsa_key.pub"],
    ["ssh-rsa", "ssh-keygen -lf /etc/ssh/ssh_host_rsa_key.pub"],
    ["rsa-sha2-512", "ssh-keygen -lf /etc/ssh/ssh_host_rsa_key.pub"],
  ])("%s → %s", (type, command) => {
    expect(fingerprintCommand(type)).toBe(command);
  });
});

describe("CHECK_LABELS", () => {
  it("names the seven checks", () => {
    expect(Object.keys(CHECK_LABELS).sort()).toEqual([
      "host_key",
      "in_log_groups",
      "not_in_docker_group",
      "not_root",
      "platform_key",
      "sudo_checker",
      "sudo_limited",
    ]);
  });
});
