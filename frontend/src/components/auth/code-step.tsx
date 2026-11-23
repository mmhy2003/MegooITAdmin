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
  onUseRecovery: () => void;
  onLocked: () => void;
  onRestart: (notice: string) => void;
};

/** The second sign-in step: the 6-digit code of the authenticator. */
export function CodeStep({ onDone, onUseRecovery, onLocked, onRestart }: Props) {
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await apiFetch("/auth/login/mfa", { body: { code, method: "totp" } });
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
          <h1 className="text-xl">Enter your code</h1>
        </CardTitle>
        <CardDescription>Enter the 6-digit code your authenticator app shows.</CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        {error && <Alert variant="destructive">{messageFor(error)}</Alert>}
        <form onSubmit={submit} className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="login-code">Code</Label>
            <Input
              id="login-code"
              inputMode="numeric"
              autoComplete="one-time-code"
              required
              value={code}
              onChange={(e) => setCode(e.target.value)}
            />
          </div>
          <Button type="submit" className="w-full" disabled={busy}>
            Verify
          </Button>
        </form>
        <div className="flex flex-wrap justify-between">
          <Button type="button" variant="link" className="px-0" onClick={onUseRecovery}>
            Use a recovery code
          </Button>
          <Button type="button" variant="link" className="px-0" onClick={() => onRestart("")}>
            Start again
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}
