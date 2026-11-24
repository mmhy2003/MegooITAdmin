"use client";

import { useEffect, useState } from "react";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Label } from "@/components/ui/label";
import { ApiError, apiFetch } from "@/lib/api";
import { messageFor, reasonText } from "@/lib/auth/messages";
import { fingerprintCommand, type HostKeyFetchResult, type Server } from "@/lib/servers";

type Props = {
  server: Server;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onPinned: (server: Server) => void;
  onStale: () => void;
};

/** Fetches a server's host key, asks the person to compare its fingerprint, then pins it. */
export function HostKeyDialog({ server, open, onOpenChange, onPinned, onStale }: Props) {
  const [attempt, setAttempt] = useState(0);
  const [notice, setNotice] = useState<string | null>(null);

  function fetchAgain(message: string | null) {
    setNotice(message);
    setAttempt((n) => n + 1);
  }

  function changeOpen(next: boolean) {
    if (!next) setNotice(null);
    onOpenChange(next);
  }

  return (
    <Dialog open={open} onOpenChange={changeOpen}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Pin the host key of {server.name}</DialogTitle>
          <DialogDescription>Nothing connects to the server until its host key is pinned.</DialogDescription>
        </DialogHeader>
        {/* Keyed by the attempt, and unmounted when closed, so each try fetches the key afresh. */}
        <PinForm
          key={attempt}
          server={server}
          notice={notice}
          onPinned={onPinned}
          onStale={onStale}
          onFetchAgain={fetchAgain}
        />
      </DialogContent>
    </Dialog>
  );
}

type FormProps = {
  server: Server;
  notice: string | null;
  onPinned: (server: Server) => void;
  onStale: () => void;
  onFetchAgain: (message: string | null) => void;
};

function PinForm({ server, notice, onPinned, onStale, onFetchAgain }: FormProps) {
  const [fetched, setFetched] = useState<HostKeyFetchResult | null>(null);
  const [compared, setCompared] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let live = true;
    apiFetch<HostKeyFetchResult>(`/servers/${server.id}/host-key/fetch`, { method: "POST" }).then(
      (result) => {
        if (live) setFetched(result);
      },
      (e: unknown) => {
        if (live) refused(e);
      },
    );
    return () => {
      live = false;
    };
    // The form is keyed by the attempt: it fetches once per mount.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function refused(e: unknown) {
    const detail = e instanceof ApiError ? e.detail : "error";
    if (detail === "stale_host_key") {
      onFetchAgain(messageFor(detail));
      return;
    }
    setError(messageFor(detail));
    const status = e instanceof ApiError ? e.status : 0;
    if (status === 403 || status === 404 || detail === "host_key_pinned" || detail === "not_an_ssh_server") {
      onStale();
    }
  }

  async function pin() {
    if (fetched?.fingerprint == null) return;
    setBusy(true);
    setError(null);
    try {
      const pinned = await apiFetch<Server>(`/servers/${server.id}/host-key`, {
        method: "PUT",
        body: { fingerprint: fetched.fingerprint },
      });
      onPinned(pinned);
    } catch (e) {
      refused(e);
    }
    setBusy(false);
  }

  const failed = fetched !== null && !fetched.ok && fetched.reason !== null ? reasonText(fetched.reason) : null;
  const key = fetched?.ok && fetched.fingerprint !== null ? fetched : null;

  return (
    <>
      {notice && <Alert>{notice}</Alert>}
      {error && <Alert variant="destructive">{error}</Alert>}
      {fetched === null && error === null && (
        <p className="text-sm text-muted-foreground">Fetching the server&apos;s key…</p>
      )}
      {failed && (
        <Alert variant="destructive">
          <AlertTitle>{failed.title}</AlertTitle>
          <AlertDescription>{failed.advice}</AlertDescription>
        </Alert>
      )}
      {key && (
        <div className="space-y-4">
          <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-sm">
            <dt className="text-muted-foreground">Fingerprint</dt>
            <dd className="font-mono break-all">{key.fingerprint}</dd>
            <dt className="text-muted-foreground">Type</dt>
            <dd>{key.type}</dd>
          </dl>
          <div className="space-y-1 text-sm">
            <p>Compare it on the server, from a console you trust:</p>
            <code className="block rounded bg-muted px-2 py-1 font-mono break-all">
              {fingerprintCommand(key.type)}
            </code>
          </div>
          <div className="flex items-center gap-2">
            <Checkbox id="host-key-compared" checked={compared} onCheckedChange={(v) => setCompared(v === true)} />
            <Label htmlFor="host-key-compared">I compared the fingerprint and it matches</Label>
          </div>
        </div>
      )}
      <DialogFooter>
        <DialogClose asChild>
          <Button variant="outline">Cancel</Button>
        </DialogClose>
        {failed && <Button onClick={() => onFetchAgain(null)}>Try again</Button>}
        {key && (
          <Button disabled={!compared || busy} onClick={pin}>
            Pin this key
          </Button>
        )}
      </DialogFooter>
    </>
  );
}
