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
import { ApiError, apiFetch } from "@/lib/api";
import { messageFor } from "@/lib/auth/messages";
import type { Server } from "@/lib/servers";

type Props = {
  server: Server | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onRemoved: () => void;
};

/** Asks before removing a server from the inventory, then removes it. */
export function RemoveServerDialog({ server, open, onOpenChange, onRemoved }: Props) {
  return (
    <Dialog open={open && server !== null} onOpenChange={onOpenChange}>
      <DialogContent>
        {/* Keyed by the server, and unmounted when closed, so an earlier refusal does not linger. */}
        {server && <RemoveConfirm key={server.id} server={server} onRemoved={onRemoved} />}
      </DialogContent>
    </Dialog>
  );
}

function RemoveConfirm({ server, onRemoved }: { server: Server; onRemoved: () => void }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function remove() {
    setBusy(true);
    setError(null);
    try {
      await apiFetch<void>(`/servers/${server.id}`, { method: "DELETE" });
      onRemoved();
    } catch (e) {
      setError(messageFor(e instanceof ApiError ? e.detail : "error"));
    }
    setBusy(false);
  }

  return (
    <>
      <DialogHeader>
        <DialogTitle>Remove {server.name}?</DialogTitle>
        <DialogDescription>It leaves the inventory for good. The audit log keeps its history.</DialogDescription>
      </DialogHeader>
      {error && <Alert variant="destructive">{error}</Alert>}
      <DialogFooter>
        <DialogClose asChild>
          <Button variant="outline">Cancel</Button>
        </DialogClose>
        <Button variant="destructive" disabled={busy} onClick={remove}>
          Remove server
        </Button>
      </DialogFooter>
    </>
  );
}
