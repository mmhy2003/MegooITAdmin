import { describe, expect, it } from "vitest";
import {
  type AccessValue,
  accessOf,
  badgesOf,
  canHold,
  type Grant,
  type GrantOut,
  inviteLink,
  PERMISSIONS,
  sameAccess,
  type Switches,
  switchesFor,
  withRole,
} from "@/lib/access";

const NONE = Object.fromEntries(PERMISSIONS.map((p) => [p, false])) as Switches;

function grant(group_id: string, role: Grant["role"], on: readonly string[] = []): Grant {
  return { group_id, role, ...NONE, ...Object.fromEntries(on.map((p) => [p, true])) };
}

describe("switchesFor", () => {
  it("ticks every switch for an Admin", () => {
    expect(switchesFor("admin")).toEqual(Object.fromEntries(PERMISSIONS.map((p) => [p, true])));
  });

  it("ticks all but managing processes and playbooks for an Operator", () => {
    expect(switchesFor("operator")).toEqual({
      connect_ssh: true,
      connect_rdp: true,
      view_logs: true,
      view_processes: true,
      manage_processes: false,
      run_playbooks: true,
      manage_playbooks: false,
    });
  });
});

describe("canHold", () => {
  it("lets an Operator hold everything but managing playbooks", () => {
    expect(canHold("operator", "manage_playbooks")).toBe(false);
    expect(canHold("operator", "manage_processes")).toBe(true);
    for (const p of PERMISSIONS) expect(canHold("admin", p)).toBe(true);
  });
});

describe("withRole", () => {
  it("sets the role and its usual switches, never managing playbooks for an Operator", () => {
    const admin = grant("g1", "admin", PERMISSIONS);
    expect(withRole(admin, "operator")).toEqual({ group_id: "g1", role: "operator", ...switchesFor("operator") });
    expect(withRole(admin, "operator").manage_playbooks).toBe(false);
    expect(withRole(grant("g1", "operator"), "admin")).toEqual({ group_id: "g1", role: "admin", ...switchesFor("admin") });
  });
});

describe("sameAccess", () => {
  const a: AccessValue = { platform_role: null, grants: [grant("g1", "admin", ["connect_ssh"]), grant("g2", "operator")] };

  it("ignores the order of the grants", () => {
    expect(sameAccess(a, { platform_role: null, grants: [...a.grants].reverse() })).toBe(true);
  });

  it("spots a switch", () => {
    expect(sameAccess(a, { ...a, grants: [grant("g1", "admin", ["connect_ssh", "view_logs"]), a.grants[1]] })).toBe(false);
  });

  it("spots a role", () => {
    expect(sameAccess(a, { ...a, grants: [grant("g1", "operator", ["connect_ssh"]), a.grants[1]] })).toBe(false);
  });

  it("spots a platform role", () => {
    expect(sameAccess({ platform_role: null, grants: [] }, { platform_role: "auditor", grants: [] })).toBe(false);
  });

  it("spots a grant more or less", () => {
    expect(sameAccess(a, { ...a, grants: [a.grants[0]] })).toBe(false);
    expect(sameAccess(a, { ...a, grants: [a.grants[0], grant("g3", "operator")] })).toBe(false);
  });
});

describe("accessOf", () => {
  it("strips the group names", () => {
    const out: GrantOut = { ...grant("g1", "admin", ["connect_ssh"]), group_name: "staging" };
    expect(accessOf({ platform_role: null, grants: [out] })).toEqual({ platform_role: null, grants: [grant("g1", "admin", ["connect_ssh"])] });
  });
});

describe("badgesOf", () => {
  it("names the platform role", () => {
    expect(badgesOf({ platform_role: "owner", grants: [] })).toEqual(["Owner"]);
    expect(badgesOf({ platform_role: "auditor", grants: [] })).toEqual(["Auditor"]);
  });

  it("names the role in each group", () => {
    const grants: GrantOut[] = [
      { ...grant("g1", "admin"), group_name: "staging" },
      { ...grant("g2", "operator"), group_name: "production" },
    ];
    expect(badgesOf({ platform_role: null, grants })).toEqual(["Admin · staging", "Operator · production"]);
  });

  it("says when there is no access", () => {
    expect(badgesOf({ platform_role: null, grants: [] })).toEqual(["No access"]);
  });
});

describe("inviteLink", () => {
  it("puts the token in the hash of /invite", () => {
    expect(inviteLink("https://a.example", "tok")).toBe("https://a.example/invite#tok");
  });
});
