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
import type { Channel } from "@/lib/alerts";
import { ApiError, apiFetch } from "@/lib/api";
import { messageFor } from "@/lib/auth/messages";

type Props = {
  channel: Channel | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onDeleted: () => void;
};

/** Names a webhook or chat and says it gets no more messages, then deletes it. */
export function DeleteChannelDialog({ channel, open, onOpenChange, onDeleted }: Props) {
  return (
    <Dialog open={open && channel !== null} onOpenChange={onOpenChange}>
      <DialogContent>
        {/* Keyed by the channel, and unmounted when closed, so an earlier refusal does not linger. */}
        {channel && <DeleteConfirm key={channel.id} channel={channel} onDeleted={onDeleted} />}
      </DialogContent>
    </Dialog>
  );
}

function DeleteConfirm({ channel, onDeleted }: { channel: Channel; onDeleted: () => void }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function remove() {
    setBusy(true);
    setError(null);
    try {
      await apiFetch<void>(`/notification-channels/${channel.id}`, { method: "DELETE" });
      onDeleted();
    } catch (e) {
      setError(messageFor(e instanceof ApiError ? e.detail : "error"));
    }
    setBusy(false);
  }

  return (
    <>
      <DialogHeader>
        <DialogTitle>Delete {channel.name}?</DialogTitle>
        <DialogDescription>It gets no more alert messages, and its saved secret is deleted with it.</DialogDescription>
      </DialogHeader>
      {error && <Alert variant="destructive">{error}</Alert>}
      <DialogFooter>
        <DialogClose asChild>
          <Button variant="outline">Cancel</Button>
        </DialogClose>
        <Button variant="destructive" disabled={busy} onClick={remove}>
          Delete channel
        </Button>
      </DialogFooter>
    </>
  );
}
