"use client";

import { useState, type FormEvent } from "react";
import { EnrolStep, type Enrolment } from "@/components/auth/enrol-step";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { ApiError, apiFetch } from "@/lib/api";
import { messageFor } from "@/lib/auth/messages";

type Props = {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onReplaced: () => void;
};

/** Replaces the authenticator: a current code, or a recovery code, comes first, then the new one is set up. */
export function AuthenticatorDialog({ open, onOpenChange, onReplaced }: Props) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        {/* The content unmounts when the dialog closes, so every opening starts again at the proof. */}
        <ReplaceAuthenticator onReplaced={onReplaced} />
      </DialogContent>
    </Dialog>
  );
}

function ReplaceAuthenticator({ onReplaced }: { onReplaced: () => void }) {
  const [enrolment, setEnrolment] = useState<Enrolment | null>(null);
  const [code, setCode] = useState("");
  const [useRecovery, setUseRecovery] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const body = await apiFetch<Enrolment>("/auth/mfa/enrol", {
        method: "POST",
        body: { code, method: useRecovery ? "recovery_code" : "totp" },
      });
      setCode("");
      setEnrolment(body);
    } catch (e) {
      setError(messageFor(e instanceof ApiError ? e.detail : "error"));
    }
    setBusy(false);
  }

  function restart(notice: string) {
    setEnrolment(null);
    setError(notice);
  }

  return (
    <>
      <DialogHeader>
        <DialogTitle>Replace authenticator</DialogTitle>
        {!enrolment && <DialogDescription>Enter a code from your current authenticator.</DialogDescription>}
      </DialogHeader>
      {enrolment ? (
        <EnrolStep enrolment={enrolment} onDone={() => onReplaced()} onRestart={restart} />
      ) : (
        <>
          {error && <Alert variant="destructive">{error}</Alert>}
          <form onSubmit={submit} className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor="replace-code">{useRecovery ? "Recovery code" : "Code"}</Label>
              <Input
                id="replace-code"
                inputMode={useRecovery ? "text" : "numeric"}
                autoComplete="one-time-code"
                required
                value={code}
                onChange={(e) => setCode(e.target.value)}
              />
            </div>
            <div className="flex items-center gap-2">
              <Checkbox
                id="replace-use-recovery"
                checked={useRecovery}
                onCheckedChange={(v) => setUseRecovery(v === true)}
              />
              <Label htmlFor="replace-use-recovery">Use a recovery code instead</Label>
            </div>
            <Button type="submit" className="w-full" disabled={busy}>
              Continue
            </Button>
          </form>
        </>
      )}
    </>
  );
}
