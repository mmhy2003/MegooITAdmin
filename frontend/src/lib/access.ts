/** The roles and grant switches of `/api/users` and `/api/server-groups`, and the rules the access form follows. */

export type PlatformRole = "owner" | "auditor";
export type GroupRole = "admin" | "operator";

export const PERMISSIONS = [
  "connect_ssh",
  "connect_rdp",
  "view_logs",
  "view_processes",
  "manage_processes",
  "run_playbooks",
  "manage_playbooks",
] as const;
export type Permission = (typeof PERMISSIONS)[number];

export const PERMISSION_LABELS: Record<Permission, string> = {
  connect_ssh: "Connect SSH",
  connect_rdp: "Connect RDP",
  view_logs: "View logs",
  view_processes: "View processes",
  manage_processes: "Manage processes",
  run_playbooks: "Run playbooks",
  manage_playbooks: "Manage playbooks",
};

export const ROLE_LABELS: Record<GroupRole | PlatformRole, string> = {
  owner: "Owner",
  auditor: "Auditor",
  admin: "Admin",
  operator: "Operator",
};

/** The switches a role ticks when it is chosen, as the backend's `USUAL`. */
export const USUAL: Record<GroupRole, readonly Permission[]> = {
  admin: PERMISSIONS,
  operator: ["connect_ssh", "connect_rdp", "view_logs", "view_processes", "run_playbooks"],
};

export type Switches = Record<Permission, boolean>;
export type Grant = { group_id: string; role: GroupRole } & Switches;
export type GrantOut = Grant & { group_name: string };
export type AccessValue = { platform_role: PlatformRole | null; grants: Grant[] };
export type UserRow = {
  id: string;
  name: string;
  email: string;
  platform_role: PlatformRole | null;
  status: "active" | "invited" | "disabled";
  mfa_enrolled: boolean;
  invite_expires_at: string | null;
  grants: GrantOut[];
};
export type ServerGroup = { id: string; name: string; description: string | null; created_at: string; member_count: number | null };
export type InviteLink = { user_id: string; token: string; expires_at: string };

/** The usual switches of `role` on, the rest off. */
export function switchesFor(role: GroupRole): Switches {
  return Object.fromEntries(PERMISSIONS.map((p) => [p, USUAL[role].includes(p)])) as Switches;
}

/** `grant` with `role` and that role's usual switches. */
export function withRole(grant: Grant, role: GroupRole): Grant {
  return { ...grant, role, ...switchesFor(role) };
}

/** Whether `role` may hold `permission`: an Operator never manages playbooks. */
export function canHold(role: GroupRole, permission: Permission): boolean {
  return !(role === "operator" && permission === "manage_playbooks");
}

function sameGrant(a: Grant, b: Grant): boolean {
  return a.role === b.role && PERMISSIONS.every((p) => a[p] === b[p]);
}

/** Whether two access values hold the same rights; grants are compared by group, in any order. */
export function sameAccess(a: AccessValue, b: AccessValue): boolean {
  if (a.platform_role !== b.platform_role || a.grants.length !== b.grants.length) return false;
  const byGroup = new Map(b.grants.map((g) => [g.group_id, g]));
  return a.grants.every((g) => {
    const other = byGroup.get(g.group_id);
    return other !== undefined && sameGrant(g, other);
  });
}

/** The access a person holds, without the group names, as `PUT /api/users/{id}/access` takes it. */
export function accessOf(user: { platform_role: PlatformRole | null; grants: Grant[] }): AccessValue {
  return {
    platform_role: user.platform_role,
    grants: user.grants.map((g) => ({
      group_id: g.group_id,
      role: g.role,
      ...(Object.fromEntries(PERMISSIONS.map((p) => [p, g[p]])) as Switches),
    })),
  };
}

/** The grants in groups that still exist: one of a group deleted meanwhile would get 422 at every save. */
export function inGroups(grants: Grant[], groups: ServerGroup[]): Grant[] {
  const ids = new Set(groups.map((g) => g.id));
  return grants.filter((g) => ids.has(g.group_id));
}

/** The badges of a person's row: their platform role, their role in each group, or "No access". */
export function badgesOf(user: { platform_role: PlatformRole | null; grants: GrantOut[] }): string[] {
  if (user.platform_role) return [ROLE_LABELS[user.platform_role]];
  if (user.grants.length === 0) return ["No access"];
  return user.grants.map((g) => `${ROLE_LABELS[g.role]} · ${g.group_name}`);
}

/** The link an invited person opens; the token sits in the hash so it never reaches a server log. */
export function inviteLink(origin: string, token: string): string {
  return `${origin}/invite#${token}`;
}
