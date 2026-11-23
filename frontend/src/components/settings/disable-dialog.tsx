"use client";

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
import type { UserRow } from "@/lib/access";
import { ApiError, apiFetch } from "@/lib/api";
import { messageFor } from "@/lib/auth/messages";

type Props = {
  user: UserRow | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onDone: () => void;
};

/** Asks the Owner before disabling a person, then disables them. */
export function DisableDialog({ user, open, onOpenChange, onDone }: Props) {
  return (
    <Dialog open={open && user !== null} onOpenChange={onOpenChange}>
      <DialogContent>
        {/* Keyed by the person, and unmounted when closed, so an earlier refusal does not linger. */}
        {user && <DisableConfirm key={user.id} user={user} onDone={onDone} />}
      </DialogContent>
    </Dialog>
  );
}

function DisableConfirm({ user, onDone }: { user: UserRow; onDone: () => void }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function disable() {
    setBusy(true);
    setError(null);
    try {
      await apiFetch<void>(`/users/${user.id}/disable`, { method: "POST" });
      onDone();
    } catch (e) {
      setError(messageFor(e instanceof ApiError ? e.detail : "error"));
    }
    setBusy(false);
  }

  return (
    <>
      <DialogHeader>
        <DialogTitle>Disable {user.name}?</DialogTitle>
        <DialogDescription>
          They are signed out at once and cannot sign in until an Owner enables the account. Their access and
          history stay.
        </DialogDescription>
      </DialogHeader>
      {error && <Alert variant="destructive">{error}</Alert>}
      <DialogFooter>
        <DialogClose asChild>
          <Button variant="outline">Cancel</Button>
        </DialogClose>
        <Button variant="destructive" disabled={busy} onClick={disable}>
          Disable
        </Button>
      </DialogFooter>
    </>
  );
}
