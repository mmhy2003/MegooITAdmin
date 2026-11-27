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
import type { AlertRule } from "@/lib/alerts";
import { ApiError, apiFetch } from "@/lib/api";
import { messageFor } from "@/lib/auth/messages";

type Props = {
  rule: AlertRule | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onDeleted: () => void;
};

/** Names an alert rule and says its firing alerts end, then deletes it. */
export function DeleteRuleDialog({ rule, open, onOpenChange, onDeleted }: Props) {
  return (
    <Dialog open={open && rule !== null} onOpenChange={onOpenChange}>
      <DialogContent>
        {/* Keyed by the rule, and unmounted when closed, so an earlier refusal does not linger. */}
        {rule && <DeleteConfirm key={rule.id} rule={rule} onDeleted={onDeleted} />}
      </DialogContent>
    </Dialog>
  );
}

function DeleteConfirm({ rule, onDeleted }: { rule: AlertRule; onDeleted: () => void }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function remove() {
    setBusy(true);
    setError(null);
    try {
      await apiFetch<void>(`/alert-rules/${rule.id}`, { method: "DELETE" });
      onDeleted();
    } catch (e) {
      setError(messageFor(e instanceof ApiError ? e.detail : "error"));
    }
    setBusy(false);
  }

  return (
    <>
      <DialogHeader>
        <DialogTitle>Delete {rule.name}?</DialogTitle>
        <DialogDescription>Its alerts that are firing now end.</DialogDescription>
      </DialogHeader>
      {error && <Alert variant="destructive">{error}</Alert>}
      <DialogFooter>
        <DialogClose asChild>
          <Button variant="outline">Cancel</Button>
        </DialogClose>
        <Button variant="destructive" disabled={busy} onClick={remove}>
          Delete rule
        </Button>
      </DialogFooter>
    </>
  );
}
