"use client";

import { useState } from "react";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import {
  Dialog, DialogClose, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle,
} from "@/components/ui/dialog";
import { ApiError } from "@/lib/api";
import { messageFor } from "@/lib/auth/messages";
import { deleteView, type LogView } from "@/lib/logs/views";

type Props = {
  view: LogView | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onDeleted: () => void;
};

/** Deletes a saved view once confirmed; what the viewer shows stays. */
export function DeleteViewDialog({ view, open, onOpenChange, onDeleted }: Props) {
  return (
    <Dialog open={open && view !== null} onOpenChange={onOpenChange}>
      <DialogContent>
        {/* Keyed by the view, and unmounted when closed, so an earlier refusal does not linger. */}
        {view && <DeleteConfirm key={view.id} view={view} onDeleted={onDeleted} />}
      </DialogContent>
    </Dialog>
  );
}

function DeleteConfirm({ view, onDeleted }: { view: LogView; onDeleted: () => void }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function remove() {
    setBusy(true);
    setError(null);
    try {
      await deleteView(view.id);
      onDeleted();
    } catch (e) {
      setError(messageFor(e instanceof ApiError ? e.detail : "error"));
    }
    setBusy(false);
  }

  return (
    <>
      <DialogHeader>
        <DialogTitle>Delete {view.name}?</DialogTitle>
        <DialogDescription>
          {view.shared ? "Nobody can open it any more, the people it is shared with included." : "You cannot open it any more."}
        </DialogDescription>
      </DialogHeader>
      {error && <Alert variant="destructive">{error}</Alert>}
      <DialogFooter>
        <DialogClose asChild>
          <Button variant="outline">Cancel</Button>
        </DialogClose>
        <Button variant="destructive" disabled={busy} onClick={remove}>Delete view</Button>
      </DialogFooter>
    </>
  );
}
