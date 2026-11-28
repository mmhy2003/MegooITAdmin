"use client";

import { useCallback, useEffect, useId, useState } from "react";
import { AllowlistDialog } from "@/components/settings/allowlist-dialog";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import {
  Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { RadioGroup, RadioGroupItem } from "@/components/ui/radio-group";
import {
  Select, SelectContent, SelectGroup, SelectItem, SelectLabel, SelectTrigger, SelectValue,
} from "@/components/ui/select";
import { apiFetch } from "@/lib/api";
import { type Container, containerTone, groupContainers, TONE_CLASSES } from "@/lib/checks";
import { matches } from "@/lib/logs/allowlist";
import {
  checkPath, checkUnit, MAX_PER_SERVER, MAX_SOURCES, PRIORITIES, wire, type LogSource, type Priority,
} from "@/lib/logs/sources";
import type { Server } from "@/lib/servers";

type Kind = "journal" | "file" | "containers";
type Allowlist = { can_manage: boolean; patterns: { id: string; pattern: string }[] };

const KINDS: [Kind, string][] = [["journal", "Journal"], ["file", "File"], ["containers", "Containers"]];
/** The value of the priority choice that sets none: Radix keeps "" for "no value". */
const ANY = "any";

type Props = {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  servers: Server[];
  /** The one server sources are added for, as on a server's Logs tab. */
  serverId?: string;
  /** The view's sources: none is added twice, and they count towards the limits. */
  current: LogSource[];
  onAdd: (added: LogSource[]) => void;
};

/** Adds a server's journal, one of its allowlisted files, or some of its containers to the view. */
export function SourceDialog({ open, onOpenChange, servers, serverId, current, onAdd }: Props) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        {/* Unmounted when closed, so it opens on a blank choice each time. */}
        {open && (
          <SourceForm servers={servers} serverId={serverId} current={current}
            onAdd={(added) => {
              onAdd(added);
              onOpenChange(false);
            }} />
        )}
      </DialogContent>
    </Dialog>
  );
}

function SourceForm({ servers, serverId, current, onAdd }: Pick<Props, "servers" | "serverId" | "current" | "onAdd">) {
  const id = useId();
  const readable = servers.filter((s) => s.os === "linux" && s.can_view_logs);
  const [chosen, setChosen] = useState<string | null>(serverId ?? null);
  const [kind, setKind] = useState<Kind>("journal");
  const [unit, setUnit] = useState("");
  const [priority, setPriority] = useState<Priority | null>(null);
  const [thisBoot, setThisBoot] = useState(false);
  const [path, setPath] = useState("");
  const [ticked, setTicked] = useState<Container[]>([]);
  const [allowlist, setAllowlist] = useState<Allowlist | null>(null);
  const target = servers.find((s) => s.id === chosen) ?? null;

  const held = new Set(current.map((s) => JSON.stringify(wire(s))));
  const isHeld = (s: LogSource) => held.has(JSON.stringify(wire(s)));

  let candidates: LogSource[] = [];
  let problem: string | null = null;
  if (chosen !== null) {
    if (kind === "journal") {
      if (unit !== "" && !checkUnit(unit)) problem = "Not a valid unit name";
      else candidates = [{ kind: "journal", server_id: chosen, unit: unit || null, priority, this_boot: thisBoot }];
    } else if (kind === "file") {
      if (path !== "" && !checkPath(path)) problem = "Not a valid path";
      else if (path !== "" && allowlist && !matches(path, allowlist.patterns.map((p) => p.pattern))) {
        problem = "This path matches none of the group's patterns.";
      } else if (path !== "" && allowlist) candidates = [{ kind: "file", server_id: chosen, path }];
    } else {
      candidates = ticked.map((c) => ({ kind: "container", server_id: chosen, container_id: c.container_id, name: c.name }));
    }
  }
  const added = candidates.filter((s) => !isHeld(s));
  if (problem === null && candidates.length > 0 && added.length === 0) problem = "The view holds this source already.";
  const onServer = current.filter((s) => s.server_id === chosen).length;
  const fits = current.length + added.length <= MAX_SOURCES && onServer + added.length <= MAX_PER_SERVER;

  // What was picked on another server does not carry over.
  function choose(next: string) {
    setChosen(next);
    setAllowlist(null);
    setTicked([]);
  }

  const groups = new Map<string, Server[]>();
  for (const s of readable) groups.set(s.group_name, [...(groups.get(s.group_name) ?? []), s]);

  return (
    <>
      <DialogHeader>
        <DialogTitle>Add source</DialogTitle>
        <DialogDescription>A view holds at most 16 sources, 8 per server.</DialogDescription>
      </DialogHeader>
      <div className="grid gap-4">
        <div className="grid gap-2">
          {serverId !== undefined ? (
            <>
              <span className="text-sm font-medium">Server</span>
              <span className="text-sm">{target?.name ?? "Unknown server"}</span>
            </>
          ) : (
            <>
              <Label htmlFor={`${id}-server`}>Server</Label>
              <Select value={chosen ?? undefined} onValueChange={choose}>
                <SelectTrigger id={`${id}-server`} aria-label="Server" className="w-full">
                  <SelectValue placeholder="Choose a server" />
                </SelectTrigger>
                <SelectContent>
                  {[...groups].map(([group, members]) => (
                    <SelectGroup key={group}>
                      <SelectLabel>{group}</SelectLabel>
                      {members.map((s) => <SelectItem key={s.id} value={s.id}>{s.name}</SelectItem>)}
                    </SelectGroup>
                  ))}
                </SelectContent>
              </Select>
            </>
          )}
        </div>
        <RadioGroup aria-label="Kind" value={kind} onValueChange={(v) => setKind(v as Kind)}
          className="flex flex-wrap gap-4">
          {KINDS.map(([k, label]) => (
            <div key={k} className="flex items-center gap-2">
              <RadioGroupItem id={`${id}-kind-${k}`} value={k} />
              <Label htmlFor={`${id}-kind-${k}`} className="font-normal">{label}</Label>
            </div>
          ))}
        </RadioGroup>
        {kind === "journal" && (
          <div className="grid gap-4">
            <div className="grid gap-2">
              <Label htmlFor={`${id}-unit`}>Unit</Label>
              <Input id={`${id}-unit`} maxLength={255} placeholder="Every unit" className="font-mono" value={unit}
                aria-invalid={problem !== null && unit !== "" ? true : undefined}
                onChange={(e) => setUnit(e.target.value)} />
            </div>
            <div className="grid gap-2">
              <Label htmlFor={`${id}-priority`}>Priority</Label>
              <Select value={priority ?? ANY} onValueChange={(v) => setPriority(v === ANY ? null : (v as Priority))}>
                <SelectTrigger id={`${id}-priority`} aria-label="Priority" className="w-full">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value={ANY}>Any</SelectItem>
                  {PRIORITIES.map((p) => <SelectItem key={p} value={p}>{`${p} and worse`}</SelectItem>)}
                </SelectContent>
              </Select>
            </div>
            <div className="flex items-center gap-2">
              <Checkbox id={`${id}-boot`} checked={thisBoot} onCheckedChange={(on) => setThisBoot(on === true)} />
              <Label htmlFor={`${id}-boot`} className="font-normal">This boot only</Label>
            </div>
          </div>
        )}
        {kind === "file" && target && (
          <FilePicker key={target.group_id} group={{ id: target.group_id, name: target.group_name }} path={path} onPath={setPath}
            invalid={problem !== null && path !== ""} allowlist={allowlist} onAllowlist={setAllowlist} />
        )}
        {kind === "containers" && target && (
          <ContainerPicker key={target.id} serverId={target.id} ticked={ticked} onTicked={setTicked}
            isHeld={(c) => isHeld({ kind: "container", server_id: target.id, container_id: c.container_id, name: null })} />
        )}
        {problem && <p className="text-sm text-destructive">{problem}</p>}
      </div>
      <DialogFooter>
        <Button disabled={problem !== null || added.length === 0 || !fits} onClick={() => onAdd(added)}>Add</Button>
      </DialogFooter>
    </>
  );
}

/** A path on the server, checked against its group's patterns, with the patterns' door for those who manage them. */
function FilePicker({ group, path, onPath, invalid, allowlist, onAllowlist }: {
  group: { id: string; name: string };
  path: string;
  onPath: (path: string) => void;
  invalid: boolean;
  allowlist: Allowlist | null;
  onAllowlist: (allowlist: Allowlist | null) => void;
}) {
  const id = useId();
  const [managing, setManaging] = useState(false);
  const [failed, setFailed] = useState(false);
  const reload = useCallback(
    () => apiFetch<Allowlist>(`/server-groups/${group.id}/log-allowlist`).then(onAllowlist, () => setFailed(true)),
    [group.id, onAllowlist],
  );
  useEffect(() => {
    void reload();
  }, [reload]);

  const patterns = allowlist?.patterns ?? [];
  // A pattern without a wildcard names one file: offered while the path typed is the start of it.
  const offered = path === "" ? [] : patterns.filter((p) => !/[*?]/.test(p.pattern) && p.pattern !== path &&
    p.pattern.startsWith(path));

  return (
    <div className="grid gap-2">
      <Label htmlFor={`${id}-path`}>Path</Label>
      <Input id={`${id}-path`} maxLength={255} placeholder="/var/log/syslog" className="font-mono" value={path}
        aria-invalid={invalid ? true : undefined} onChange={(e) => onPath(e.target.value)} />
      {offered.length > 0 && (
        <div className="flex flex-wrap gap-1">
          {offered.map((p) => (
            <Button key={p.id} size="xs" variant="outline" className="font-mono" onClick={() => onPath(p.pattern)}>
              {p.pattern}
            </Button>
          ))}
        </div>
      )}
      {failed && <p className="text-sm text-destructive">The group&apos;s patterns could not be read.</p>}
      {allowlist && (
        <div className="grid gap-1">
          <div className="flex items-center justify-between gap-2">
            <span id={`${id}-patterns`} className="text-sm text-muted-foreground">Patterns of {group.name}</span>
            {allowlist.can_manage && (
              <Button size="xs" variant="outline" onClick={() => setManaging(true)}>Manage patterns</Button>
            )}
          </div>
          {patterns.length > 0 ? (
            <ul aria-labelledby={`${id}-patterns`} className="font-mono text-sm break-all text-muted-foreground">
              {patterns.map((p) => <li key={p.id}>{p.pattern}</li>)}
            </ul>
          ) : (
            <p className="text-sm text-muted-foreground">This group has no patterns yet.</p>
          )}
        </div>
      )}
      <AllowlistDialog group={group} open={managing} onOpenChange={(next) => {
        setManaging(next);
        if (!next) void reload();
      }} />
    </div>
  );
}

/** The server's containers by Compose project, each with its state; those the view holds show ticked and fixed. */
function ContainerPicker({ serverId, ticked, onTicked, isHeld }: {
  serverId: string;
  ticked: Container[];
  onTicked: (ticked: Container[]) => void;
  isHeld: (c: Container) => boolean;
}) {
  const id = useId();
  const [containers, setContainers] = useState<Container[] | null>(null);
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    apiFetch<Container[]>(`/servers/${serverId}/containers`).then(setContainers, () => setFailed(true));
  }, [serverId]);

  if (failed) return <p className="text-sm text-destructive">The server&apos;s containers could not be read.</p>;
  if (containers === null) return <p className="text-sm text-muted-foreground">Reading the containers…</p>;
  if (containers.length === 0) return <p className="text-sm text-muted-foreground">No containers on this server.</p>;

  const isTicked = (c: Container) => ticked.some((t) => t.container_id === c.container_id);
  const toggle = (c: Container, on: boolean) =>
    onTicked(on ? [...ticked, c] : ticked.filter((t) => t.container_id !== c.container_id));

  return (
    <div className="grid max-h-72 gap-3 overflow-y-auto">
      {groupContainers(containers).map((group) => {
        const title = group.project ?? "No Compose project";
        return (
          <div key={group.project ?? ""} role="group" aria-label={title} className="grid gap-1">
            <span className="text-sm font-medium">{title}</span>
            {group.containers.map((c) => {
              const held = isHeld(c);
              return (
                <div key={c.container_id} className="flex items-center gap-2">
                  <Checkbox id={`${id}-${c.container_id}`} aria-label={c.name} checked={held || isTicked(c)}
                    disabled={held} onCheckedChange={(on) => toggle(c, on === true)} />
                  <Label htmlFor={`${id}-${c.container_id}`} className="font-mono font-normal">{c.name}</Label>
                  <Badge variant="outline" className={TONE_CLASSES[containerTone(c.state)]}>{c.state}</Badge>
                </div>
              );
            })}
          </div>
        );
      })}
    </div>
  );
}
