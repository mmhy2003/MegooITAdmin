"use client";

import { useState, type FormEvent } from "react";
import { AccessForm } from "@/components/settings/access-form";
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
import { accessOf, type AccessValue, inGroups, sameAccess, type ServerGroup, type UserRow } from "@/lib/access";
import { ApiError, apiFetch } from "@/lib/api";
import { messageFor } from "@/lib/auth/messages";

type Props = {
  user: UserRow | null;
  groups: ServerGroup[];
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onSaved: () => void;
  onStale: () => void;
};

/** Changes a person's platform role or their role and switches in each server group. */
export function AccessDialog({ user, groups, open, onOpenChange, onSaved, onStale }: Props) {
  return (
    <Dialog open={open && user !== null} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-3xl">
        {/* Keyed by the person, and unmounted when closed, so the form always starts from their saved access. */}
        {user && <AccessChange key={user.id} user={user} groups={groups} onSaved={onSaved} onStale={onStale} />}
      </DialogContent>
    </Dialog>
  );
}

function AccessChange({
  user,
  groups,
  onSaved,
  onStale,
}: Pick<Props, "groups" | "onSaved" | "onStale"> & { user: UserRow }) {
  const [initial] = useState(() => accessOf(user));
  const [access, setAccess] = useState<AccessValue>(initial);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await apiFetch<void>(`/users/${user.id}/access`, {
        method: "PUT",
        body: { platform_role: access.platform_role, grants: inGroups(access.grants, groups) },
      });
      onSaved();
    } catch (e) {
      const detail = e instanceof ApiError ? e.detail : "error";
      // A 422 most likely names a group that was deleted meanwhile: the page fetches the groups again.
      if (e instanceof ApiError && e.status === 422) onStale();
      setError(messageFor(detail));
    }
    setBusy(false);
  }

  return (
    <>
      <DialogHeader>
        <DialogTitle>Change access of {user.name}</DialogTitle>
        <DialogDescription>Choose a platform role, or a role and its switches in each server group.</DialogDescription>
      </DialogHeader>
      <form onSubmit={submit} className="grid max-h-[70vh] gap-4 overflow-y-auto">
        {error && <Alert variant="destructive">{error}</Alert>}
        <AccessForm value={access} groups={groups} onChange={setAccess} />
        <DialogFooter>
          <Button type="submit" disabled={busy || sameAccess(initial, access)}>
            Save
          </Button>
        </DialogFooter>
      </form>
    </>
  );
}
