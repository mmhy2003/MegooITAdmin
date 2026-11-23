"use client";

import Link from "next/link";
import { useId, useRef } from "react";
import { Checkbox } from "@/components/ui/checkbox";
import { Label } from "@/components/ui/label";
import { RadioGroup, RadioGroupItem } from "@/components/ui/radio-group";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import {
  type AccessValue,
  canHold,
  type Grant,
  type GroupRole,
  PERMISSION_LABELS,
  PERMISSIONS,
  type PlatformRole,
  type ServerGroup,
  switchesFor,
  withRole,
} from "@/lib/access";

type Props = {
  value: AccessValue;
  groups: ServerGroup[];
  onChange: (value: AccessValue) => void;
};

type Kind = "groups" | PlatformRole;

const NO_ACCESS = "none";

const KINDS: { kind: Kind; label: string }[] = [
  { kind: "groups", label: "By server group" },
  { kind: "auditor", label: "Auditor" },
  { kind: "owner", label: "Owner" },
];

const PLATFORM_LINES: Record<PlatformRole, string> = {
  auditor: "Reads dashboards, reports, recordings and the audit log in every group. Holds none of the grants.",
  owner: "Runs the platform: people, settings and every group.",
};

/** The access of one person: a platform role, or a role and seven switches in each server group. */
export function AccessForm({ value, groups, onChange }: Props) {
  const id = useId();
  // The rows as they were before Auditor or Owner was chosen, so "By server group" brings them back.
  const keptGrants = useRef<Grant[]>(value.grants);
  const kind: Kind = value.platform_role ?? "groups";

  function chooseKind(next: string) {
    if (next === kind) return;
    if (kind === "groups") keptGrants.current = value.grants;
    if (next === "groups") onChange({ platform_role: null, grants: keptGrants.current });
    else onChange({ platform_role: next as PlatformRole, grants: [] });
  }

  function chooseRole(group: ServerGroup, role: string) {
    const others = value.grants.filter((g) => g.group_id !== group.id);
    const current = value.grants.find((g) => g.group_id === group.id);
    if (role === NO_ACCESS) {
      onChange({ ...value, grants: others });
      return;
    }
    const r = role as GroupRole;
    if (current) onChange({ ...value, grants: value.grants.map((g) => (g === current ? withRole(g, r) : g)) });
    else onChange({ ...value, grants: [...others, { group_id: group.id, role: r, ...switchesFor(r) }] });
  }

  function toggle(grant: Grant, permission: (typeof PERMISSIONS)[number], on: boolean) {
    onChange({ ...value, grants: value.grants.map((g) => (g === grant ? { ...g, [permission]: on } : g)) });
  }

  return (
    <div className="grid gap-4">
      <div className="grid gap-2">
        <Label id={`${id}-kind`}>Access</Label>
        <RadioGroup aria-labelledby={`${id}-kind`} value={kind} onValueChange={chooseKind} className="flex flex-wrap gap-4">
          {KINDS.map(({ kind: k, label }) => (
            <div key={k} className="flex items-center gap-2">
              <RadioGroupItem id={`${id}-kind-${k}`} value={k} />
              <Label htmlFor={`${id}-kind-${k}`} className="font-normal">
                {label}
              </Label>
            </div>
          ))}
        </RadioGroup>
      </div>

      {kind !== "groups" ? (
        <p className="text-sm text-muted-foreground">{PLATFORM_LINES[kind]}</p>
      ) : groups.length === 0 ? (
        <p className="text-sm text-muted-foreground">
          No server groups yet. Create one on the{" "}
          <Link href="/settings/groups" className="underline underline-offset-4">
            Server groups
          </Link>{" "}
          tab.
        </p>
      ) : (
        <div className="grid gap-3">
          {groups.map((group) => {
            const grant = value.grants.find((g) => g.group_id === group.id);
            return (
              <div
                key={group.id}
                className="grid gap-3 rounded-md border p-3 md:grid-cols-[10rem_10rem_1fr] md:items-start"
              >
                <span className="text-sm font-medium break-words">{group.name}</span>
                <Select value={grant?.role ?? NO_ACCESS} onValueChange={(role) => chooseRole(group, role)}>
                  <SelectTrigger aria-label={`Role in ${group.name}`} className="w-full">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value={NO_ACCESS}>No access</SelectItem>
                    <SelectItem value="admin">Admin</SelectItem>
                    <SelectItem value="operator">Operator</SelectItem>
                  </SelectContent>
                </Select>
                <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
                  {PERMISSIONS.map((permission) => {
                    const boxId = `${id}-${group.id}-${permission}`;
                    return (
                      <div key={permission} className="flex items-center gap-2">
                        <Checkbox
                          id={boxId}
                          aria-label={`${PERMISSION_LABELS[permission]} in ${group.name}`}
                          checked={grant?.[permission] ?? false}
                          disabled={!grant || !canHold(grant.role, permission)}
                          onCheckedChange={(on) => grant && toggle(grant, permission, on === true)}
                        />
                        <Label htmlFor={boxId} className="font-normal">
                          {PERMISSION_LABELS[permission]}
                        </Label>
                      </div>
                    );
                  })}
                </div>
              </div>
            );
          })}
          <p className="text-sm text-muted-foreground">
            Only Connect SSH and Connect RDP are checked by the app for now. The other switches are saved for the
            features that come later.
          </p>
        </div>
      )}
    </div>
  );
}
