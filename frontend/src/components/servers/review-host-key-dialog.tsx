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
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { ApiError, apiFetch } from "@/lib/api";
import { messageFor } from "@/lib/auth/messages";
import type { Server } from "@/lib/servers";

type Props = {
  server: Server;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onDone: (server: Server) => void;
  onStale: () => void;
};

/** Refusals that mean the page no longer shows the server as it is. */
const STALE = new Set(["stale_host_key", "host_key_not_changed", "not_an_ssh_server"]);

/** Shows the pinned and the presented host key, then accepts the new one with a reason or keeps the pinned one. */
export function ReviewHostKeyDialog({ server, open, onOpenChange, onDone, onStale }: Props) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Review the host key of {server.name}</DialogTitle>
          <DialogDescription>Connections to the server stay blocked until its host key is reviewed.</DialogDescription>
        </DialogHeader>
        {/* Unmounted when closed, so each review starts without a reason or an error. */}
        <ReviewForm server={server} onDone={onDone} onStale={onStale} />
      </DialogContent>
    </Dialog>
  );
}

type FormProps = {
  server: Server;
  onDone: (server: Server) => void;
  onStale: () => void;
};

function ReviewForm({ server, onDone, onStale }: FormProps) {
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const offered = server.host_key_offered;

  async function review(request: () => Promise<Server>) {
    setBusy(true);
    setError(null);
    try {
      onDone(await request());
    } catch (e) {
      const detail = e instanceof ApiError ? e.detail : "error";
      const status = e instanceof ApiError ? e.status : 0;
      setError(messageFor(detail));
      if (status === 403 || status === 404 || (status === 409 && STALE.has(detail))) onStale();
    }
    setBusy(false);
  }

  function keep() {
    return review(() => apiFetch<Server>(`/servers/${server.id}/host-key/keep`, { method: "POST" }));
  }

  function accept() {
    if (offered === null) return;
    return review(() =>
      apiFetch<Server>(`/servers/${server.id}/host-key`, {
        method: "PUT",
        body: { fingerprint: offered.fingerprint, reason },
      }),
    );
  }

  return (
    <>
      {error && <Alert variant="destructive">{error}</Alert>}
      <div className="space-y-4">
        <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-sm">
          <dt className="text-muted-foreground">Pinned key</dt>
          <dd className="font-mono break-all">{server.host_key_fingerprint}</dd>
          <dt className="text-muted-foreground">Presented key</dt>
          {offered ? (
            <dd className="font-mono break-all">{offered.fingerprint}</dd>
          ) : (
            <dd>Could not be read</dd>
          )}
        </dl>
        {offered && (
          <div className="space-y-2">
            <Label htmlFor="host-key-reason">Why you accept the new key</Label>
            <Input id="host-key-reason" value={reason} onChange={(e) => setReason(e.target.value)} />
          </div>
        )}
      </div>
      <DialogFooter>
        <DialogClose asChild>
          <Button variant="outline">Cancel</Button>
        </DialogClose>
        <Button variant="outline" disabled={busy} onClick={keep}>
          Keep the pinned key
        </Button>
        {offered && (
          <Button disabled={busy || reason.trim() === ""} onClick={accept}>
            Accept the new key
          </Button>
        )}
      </DialogFooter>
    </>
  );
}
