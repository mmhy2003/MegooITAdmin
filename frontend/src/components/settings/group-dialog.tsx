"use client";

import { useState, type FormEvent } from "react";
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
import type { ServerGroup } from "@/lib/access";
import { ApiError, apiFetch } from "@/lib/api";
import { messageFor } from "@/lib/auth/messages";

type Props = {
  group?: ServerGroup | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onSaved: () => void;
};

/** Creates a server group, or edits the name and description of `group`. */
export function GroupDialog({ group, open, onOpenChange, onSaved }: Props) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        {/* Keyed by the group, and unmounted when closed, so the form always starts from the saved group. */}
        <GroupForm key={group?.id ?? "new"} group={group ?? null} onSaved={onSaved} />
      </DialogContent>
    </Dialog>
  );
}

function GroupForm({ group, onSaved }: { group: ServerGroup | null; onSaved: () => void }) {
  const [name, setName] = useState(group?.name ?? "");
  const [description, setDescription] = useState(group?.description ?? "");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // The backend trims both fields and stores an empty description as none.
  const unchanged =
    group !== null && name.trim() === group.name && description.trim() === (group.description ?? "");

  async function submit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      if (group) {
        await apiFetch<ServerGroup>(`/server-groups/${group.id}`, { method: "PATCH", body: { name, description } });
      } else {
        await apiFetch<ServerGroup>("/server-groups", { method: "POST", body: { name, description } });
      }
      onSaved();
    } catch (e) {
      setError(messageFor(e instanceof ApiError ? e.detail : "error"));
    }
    setBusy(false);
  }

  return (
    <>
      <DialogHeader>
        <DialogTitle>{group ? `Edit ${group.name}` : "New server group"}</DialogTitle>
        <DialogDescription>People get roles per server group, and later its servers live in it.</DialogDescription>
      </DialogHeader>
      <form onSubmit={submit} className="grid gap-4">
        {error && <Alert variant="destructive">{error}</Alert>}
        <div className="space-y-2">
          <Label htmlFor="group-name">Name</Label>
          <Input
            id="group-name"
            required
            maxLength={64}
            aria-describedby="group-name-hint"
            value={name}
            onChange={(e) => setName(e.target.value)}
          />
          <p id="group-name-hint" className="text-sm text-muted-foreground">
            1 to 64 characters.
          </p>
        </div>
        <div className="space-y-2">
          <Label htmlFor="group-description">Description</Label>
          <Input
            id="group-description"
            maxLength={500}
            value={description}
            onChange={(e) => setDescription(e.target.value)}
          />
        </div>
        <DialogFooter>
          <Button type="submit" disabled={busy || unchanged}>
            {group ? "Save" : "Create group"}
          </Button>
        </DialogFooter>
      </form>
    </>
  );
}
