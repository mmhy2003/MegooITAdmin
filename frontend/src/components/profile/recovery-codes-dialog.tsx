"use client";

import { useState, type FormEvent } from "react";
import { RecoveryCodes } from "@/components/auth/recovery-codes";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { ApiError, apiFetch } from "@/lib/api";
import { messageFor } from "@/lib/auth/messages";

type Props = {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onCreated: () => void;
};

/** Creates 10 new recovery codes after a current code; the old ones stop working. */
export function RecoveryCodesDialog({ open, onOpenChange, onCreated }: Props) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        {/* The codes are shown once: the content unmounts when the dialog closes, and forgets them. */}
        <NewRecoveryCodes
          onDone={() => {
            onCreated();
            onOpenChange(false);
          }}
        />
      </DialogContent>
    </Dialog>
  );
}

function NewRecoveryCodes({ onDone }: { onDone: () => void }) {
  const [codes, setCodes] = useState<string[] | null>(null);
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const body = await apiFetch<{ recovery_codes: string[] }>("/auth/recovery-codes", {
        method: "POST",
        body: { code },
      });
      setCode("");
      setCodes(body.recovery_codes);
    } catch (e) {
      setError(messageFor(e instanceof ApiError ? e.detail : "error"));
    }
    setBusy(false);
  }

  return (
    <>
      <DialogHeader>
        <DialogTitle>New recovery codes</DialogTitle>
        {!codes && (
          <DialogDescription>Enter a code from your authenticator. The old codes stop working.</DialogDescription>
        )}
      </DialogHeader>
      {codes ? (
        <RecoveryCodes codes={codes} continueLabel="Done" onContinue={onDone} />
      ) : (
        <>
          {error && <Alert variant="destructive">{error}</Alert>}
          <form onSubmit={submit} className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor="new-codes-code">Code</Label>
              <Input
                id="new-codes-code"
                inputMode="numeric"
                autoComplete="one-time-code"
                required
                value={code}
                onChange={(e) => setCode(e.target.value)}
              />
            </div>
            <Button type="submit" className="w-full" disabled={busy}>
              Create codes
            </Button>
          </form>
        </>
      )}
    </>
  );
}
