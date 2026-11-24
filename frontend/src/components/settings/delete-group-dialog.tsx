"use client";

import Link from "next/link";
import { useState } from "react";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import type { ServerGroup } from "@/lib/access";
import { ApiError, apiFetch } from "@/lib/api";
import { messageFor } from "@/lib/auth/messages";

type Props = {
  group: ServerGroup | null;
  /** The names of the people who hold a role in the group. */
  people: string[];
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onDeleted: () => void;
};

/** Names the people who lose their role in a server group, then deletes it; refuses while the group holds servers. */
export function DeleteGroupDialog({ group, people, open, onOpenChange, onDeleted }: Props) {
  return (
    <Dialog open={open && group !== null} onOpenChange={onOpenChange}>
      <DialogContent>
        {/* Keyed by the group, and unmounted when closed, so an earlier refusal does not linger. */}
        {group &&
          (group.server_count > 0 ? (
            <HoldsServers group={group} />
          ) : (
            <DeleteConfirm key={group.id} group={group} people={people} onDeleted={onDeleted} />
          ))}
      </DialogContent>
    </Dialog>
  );
}

function HoldsServers({ group }: { group: ServerGroup }) {
  const servers = group.server_count === 1 ? "server" : "servers";
  return (
    <>
      <DialogHeader>
        <DialogTitle>{group.name} still holds servers</DialogTitle>
        <DialogDescription>
          Move or remove its {group.server_count} {servers} first. A group that holds servers cannot be deleted.
        </DialogDescription>
      </DialogHeader>
      <DialogFooter>
        <Button variant="outline" asChild>
          <Link href={`/servers?group=${group.id}`}>Show its servers</Link>
        </Button>
        <DialogClose asChild>
          <Button>Close</Button>
        </DialogClose>
      </DialogFooter>
    </>
  );
}

function DeleteConfirm({ group, people, onDeleted }: { group: ServerGroup; people: string[]; onDeleted: () => void }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function remove() {
    setBusy(true);
    setError(null);
    try {
      await apiFetch<void>(`/server-groups/${group.id}`, { method: "DELETE" });
      onDeleted();
    } catch (e) {
      setError(messageFor(e instanceof ApiError ? e.detail : "error"));
    }
    setBusy(false);
  }

  return (
    <>
      <DialogHeader>
        <DialogTitle>Delete {group.name}?</DialogTitle>
        <DialogDescription>
          {people.length > 0
            ? `These people lose their role in it: ${people.join(", ")}.`
            : "Nobody holds a role in it."}
        </DialogDescription>
      </DialogHeader>
      {error && <Alert variant="destructive">{error}</Alert>}
      <DialogFooter>
        <DialogClose asChild>
          <Button variant="outline">Cancel</Button>
        </DialogClose>
        <Button variant="destructive" disabled={busy} onClick={remove}>
          Delete group
        </Button>
      </DialogFooter>
    </>
  );
}
