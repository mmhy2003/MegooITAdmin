"use client";

import { useState, type FormEvent } from "react";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { ApiError, apiFetch } from "@/lib/api";
import { messageFor } from "@/lib/auth/messages";

type Props = {
  onDone: () => void;
  onUseCode: () => void;
  onLocked: () => void;
  onRestart: (notice: string) => void;
};

/** The second sign-in step without the authenticator: one of the saved recovery codes. */
export function RecoveryStep({ onDone, onUseCode, onLocked, onRestart }: Props) {
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await apiFetch("/auth/login/mfa", { body: { code, method: "recovery_code" } });
      onDone();
      return;
    } catch (e) {
      const detail = e instanceof ApiError ? e.detail : "error";
      if (detail === "locked") return onLocked();
      if (detail === "not_signed_in") return onRestart(messageFor("not_signed_in"));
      setError(detail);
    }
    setBusy(false);
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>
          <h1 className="text-xl">Use a recovery code</h1>
        </CardTitle>
        <CardDescription>Enter one of the recovery codes you saved. Each code works once.</CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        {error && <Alert variant="destructive">{messageFor(error)}</Alert>}
        <form onSubmit={submit} className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="login-recovery-code">Recovery code</Label>
            <Input
              id="login-recovery-code"
              autoComplete="off"
              autoCapitalize="characters"
              spellCheck={false}
              placeholder="XXXX-XXXX-XXXX-XXXX"
              className="font-mono"
              required
              value={code}
              onChange={(e) => setCode(e.target.value)}
            />
          </div>
          <Button type="submit" className="w-full" disabled={busy}>
            Verify
          </Button>
        </form>
        <Button type="button" variant="link" className="px-0" onClick={onUseCode}>
          Use your authenticator instead
        </Button>
      </CardContent>
    </Card>
  );
}
