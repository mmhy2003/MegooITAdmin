"use client";

import { useState, type FormEvent } from "react";
import { TagInput } from "@/components/servers/tag-input";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { RadioGroup, RadioGroupItem } from "@/components/ui/radio-group";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import type { ServerGroup } from "@/lib/access";
import { ApiError, apiFetch } from "@/lib/api";
import { messageFor } from "@/lib/auth/messages";
import {
  bodyOf,
  changesOf,
  DEFAULT_INTERVAL,
  DEFAULT_PORT,
  draftOf,
  OS_LABELS,
  type Server,
  type ServerDraft,
  type ServerOs,
} from "@/lib/servers";

type Props = {
  server: Server | null;
  /** The groups the person may manage. */
  groups: ServerGroup[];
  defaultGroupId: string | null;
  /** The tags in use, offered while typing. */
  tags: string[];
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onSaved: (server: Server) => void;
  /** The rights or the groups changed under the dialog: the page reloads them. */
  onStale: () => void;
};

const OSES = Object.keys(OS_LABELS) as ServerOs[];
/** Answers that mean the page shows what is no longer true. */
const STALE_STATUSES = [403, 404];

/** Registers a server, or edits `server`. */
export function ServerDialog({ server, groups, defaultGroupId, tags, open, onOpenChange, onSaved, onStale }: Props) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-xl">
        {/* Keyed by the server, and unmounted when closed, so the form always starts from the saved server. */}
        <ServerForm
          key={server?.id ?? "new"}
          server={server}
          groups={groups}
          groupId={defaultGroupId ?? groups[0]?.id ?? ""}
          tags={tags}
          onSaved={onSaved}
          onStale={onStale}
        />
      </DialogContent>
    </Dialog>
  );
}

type FormProps = Pick<Props, "server" | "groups" | "tags" | "onSaved" | "onStale"> & { groupId: string };

function ServerForm({ server, groups, groupId, tags, onSaved, onStale }: FormProps) {
  const [draft, setDraft] = useState<ServerDraft>(() => draftOf(server, groupId));
  // A port other than the usual one of its OS was chosen on purpose, so the OS no longer moves it.
  const [portEdited, setPortEdited] = useState(draft.port !== DEFAULT_PORT[draft.os]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const changes = server ? changesOf(server, draft) : null;
  const unchanged = changes !== null && Object.keys(changes).length === 0;
  const target = server && draft.group_id !== server.group_id ? groups.find((g) => g.id === draft.group_id) : null;

  function set<K extends keyof ServerDraft>(key: K, value: ServerDraft[K]) {
    setDraft((d) => ({ ...d, [key]: value }));
  }

  function chooseOs(os: ServerOs) {
    setDraft((d) => ({
      ...d,
      os,
      port: portEdited ? d.port : DEFAULT_PORT[os],
      // Windows is not sampled: it keeps the saved interval, so the hidden field changes nothing.
      interval: os === "windows" ? (server?.metrics_interval_seconds ?? DEFAULT_INTERVAL) : d.interval,
    }));
  }

  async function submit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const saved = server
        ? await apiFetch<Server>(`/servers/${server.id}`, { method: "PATCH", body: changes })
        : await apiFetch<Server>("/servers", { method: "POST", body: bodyOf(draft) });
      onSaved(saved);
    } catch (e) {
      const detail = e instanceof ApiError ? e.detail : "error";
      setError(messageFor(detail));
      if (e instanceof ApiError && (STALE_STATUSES.includes(e.status) || detail === "unknown_group")) onStale();
    }
    setBusy(false);
  }

  return (
    <>
      <DialogHeader>
        <DialogTitle>{server ? `Edit ${server.name}` : "Register a server"}</DialogTitle>
        <DialogDescription>Everyone with a role in its server group sees it.</DialogDescription>
      </DialogHeader>
      <form onSubmit={submit} className="grid gap-4">
        {error && <Alert variant="destructive">{error}</Alert>}
        <div className="space-y-2">
          <Label htmlFor="server-name">Name</Label>
          <Input
            id="server-name"
            required
            maxLength={64}
            pattern="[A-Za-z0-9][A-Za-z0-9._\-]*"
            aria-describedby="server-name-hint"
            value={draft.name}
            onChange={(e) => set("name", e.target.value)}
          />
          <p id="server-name-hint" className="text-sm text-muted-foreground">
            Letters, digits, dots, dashes and underscores; unique across all groups.
          </p>
        </div>
        <div className="grid gap-4 sm:grid-cols-2">
          <div className="space-y-2">
            <Label htmlFor="server-address">Address</Label>
            <Input
              id="server-address"
              required
              maxLength={253}
              placeholder="10.0.0.5 or host.example.com"
              value={draft.address}
              onChange={(e) => set("address", e.target.value)}
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="server-port">Port</Label>
            <Input
              id="server-port"
              type="number"
              required
              min={1}
              max={65535}
              value={Number.isNaN(draft.port) ? "" : draft.port}
              onChange={(e) => {
                setPortEdited(true);
                set("port", e.target.valueAsNumber);
              }}
            />
          </div>
        </div>
        <div className="space-y-2">
          <Label htmlFor="server-group">Server group</Label>
          <Select value={draft.group_id} onValueChange={(id) => set("group_id", id)}>
            <SelectTrigger id="server-group" aria-label="Server group" className="w-full">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {groups.map((g) => (
                <SelectItem key={g.id} value={g.id}>
                  {g.name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          {server && target && (
            <Alert>
              {`Moving ${server.name} to ${target.name} changes who sees it: the people of ${server.group_name} lose it and those of ${target.name} get it.`}
            </Alert>
          )}
        </div>
        <div className="grid gap-4 sm:grid-cols-2">
          <div className="space-y-2">
            <Label id="server-os">Operating system</Label>
            <RadioGroup
              aria-labelledby="server-os"
              value={draft.os}
              onValueChange={(os) => chooseOs(os as ServerOs)}
              className="flex h-9 flex-wrap items-center gap-4"
            >
              {OSES.map((os) => (
                <div key={os} className="flex items-center gap-2">
                  <RadioGroupItem id={`server-os-${os}`} value={os} />
                  <Label htmlFor={`server-os-${os}`} className="font-normal">
                    {OS_LABELS[os]}
                  </Label>
                </div>
              ))}
            </RadioGroup>
          </div>
          <div className="space-y-2">
            <Label htmlFor="server-username">Login account</Label>
            <Input
              id="server-username"
              required
              maxLength={64}
              pattern="\S+"
              value={draft.username}
              onChange={(e) => set("username", e.target.value)}
            />
          </div>
        </div>
        <div className="grid gap-4 sm:grid-cols-2">
          <div className="space-y-2">
            <Label htmlFor="server-role">Role</Label>
            <Input
              id="server-role"
              maxLength={64}
              placeholder="web, database…"
              value={draft.role}
              onChange={(e) => set("role", e.target.value)}
            />
          </div>
          {draft.os === "linux" && (
            <div className="space-y-2">
              <Label htmlFor="server-interval">Sample interval</Label>
              <div className="flex items-center gap-2">
                <Input
                  id="server-interval"
                  type="number"
                  required
                  min={1}
                  max={10}
                  step={1}
                  className="w-24"
                  aria-describedby="server-interval-hint"
                  value={Number.isNaN(draft.interval) ? "" : draft.interval}
                  onChange={(e) => set("interval", e.target.valueAsNumber)}
                />
                <span className="text-sm text-muted-foreground">seconds</span>
              </div>
              <p id="server-interval-hint" className="text-sm text-muted-foreground">
                How often its metrics are read: 1 to 10 seconds.
              </p>
            </div>
          )}
        </div>
        <div className="space-y-2">
          <Label htmlFor="server-tags">Tags</Label>
          <TagInput id="server-tags" value={draft.tags} onChange={(t) => set("tags", t)} suggestions={tags} />
        </div>
        <DialogFooter>
          <Button type="submit" disabled={busy || unchanged}>
            {server ? "Save" : "Register server"}
          </Button>
        </DialogFooter>
      </form>
    </>
  );
}
