"use client";

import { Trash2 } from "lucide-react";
import { useCallback, useEffect, useState, type FormEvent } from "react";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { ApiError, apiFetch } from "@/lib/api";
import { messageFor } from "@/lib/auth/messages";
import { checkPattern } from "@/lib/logs/allowlist";

type Group = { id: string; name: string };
type Pattern = { id: string; pattern: string; created_at: string };
type Allowlist = { can_manage: boolean; patterns: Pattern[] };

type Props = {
  group: Group | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
};

/** Lists the log file patterns of `group`; the Owner and the group's Admins add and remove them. */
export function AllowlistDialog({ group, open, onOpenChange }: Props) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        {/* Keyed by the group, and unmounted when closed, so it always reads the group's patterns afresh. */}
        {group && <AllowlistBody key={group.id} group={group} />}
      </DialogContent>
    </Dialog>
  );
}

function AllowlistBody({ group }: { group: Group }) {
  const [allowlist, setAllowlist] = useState<Allowlist | null>(null);
  const [pattern, setPattern] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const path = `/server-groups/${group.id}/log-allowlist`;

  const reload = useCallback(
    () =>
      apiFetch<Allowlist>(path).then(setAllowlist, (e: unknown) =>
        setError(messageFor(e instanceof ApiError ? e.detail : "error")),
      ),
    [path],
  );

  useEffect(() => {
    void reload();
  }, [reload]);

  async function change(request: () => Promise<unknown>) {
    setBusy(true);
    setError(null);
    try {
      await request();
      await reload();
      setBusy(false);
      return true;
    } catch (e) {
      setError(messageFor(e instanceof ApiError ? e.detail : "error"));
      setBusy(false);
      return false;
    }
  }

  async function add(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    if (!checkPattern(pattern)) {
      setError("Not a valid pattern");
      return;
    }
    if (await change(() => apiFetch<Pattern>(path, { method: "POST", body: { pattern } }))) setPattern("");
  }

  return (
    <>
      <DialogHeader>
        <DialogTitle>Log file patterns of {group.name}</DialogTitle>
        <DialogDescription>
          People with View logs follow the files of this group&apos;s servers that match a pattern. A wildcard stays
          inside one path segment: * is any characters, ? is one.
        </DialogDescription>
      </DialogHeader>
      <div className="grid gap-4">
        {error && <Alert variant="destructive">{error}</Alert>}
        {allowlist &&
          (allowlist.patterns.length ? (
            <ul aria-label="Patterns" className="divide-y rounded-md border">
              {allowlist.patterns.map((p) => (
                <li key={p.id} className="flex items-center justify-between gap-2 px-3 py-1">
                  <span className="font-mono text-sm break-all">{p.pattern}</span>
                  {allowlist.can_manage && (
                    <Button
                      variant="ghost"
                      size="icon"
                      aria-label={`Remove ${p.pattern}`}
                      disabled={busy}
                      onClick={() => void change(() => apiFetch(`${path}/${p.id}`, { method: "DELETE" }))}
                    >
                      <Trash2 aria-hidden />
                    </Button>
                  )}
                </li>
              ))}
            </ul>
          ) : (
            <p className="text-sm text-muted-foreground">This group has no patterns yet.</p>
          ))}
        {allowlist?.can_manage && (
          <form onSubmit={add} className="flex items-end gap-2">
            <div className="flex-1 space-y-2">
              <Label htmlFor="allowlist-pattern">Pattern</Label>
              <Input
                id="allowlist-pattern"
                required
                maxLength={255}
                placeholder="/var/log/nginx/*.log"
                className="font-mono"
                value={pattern}
                onChange={(e) => setPattern(e.target.value)}
              />
            </div>
            <Button type="submit" disabled={busy}>
              Add
            </Button>
          </form>
        )}
      </div>
    </>
  );
}
