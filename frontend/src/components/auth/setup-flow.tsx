"use client";

import { useState, type FormEvent } from "react";
import { EnrolStep } from "@/components/auth/enrol-step";
import { RecoveryCodes } from "@/components/auth/recovery-codes";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { ApiError, apiFetch } from "@/lib/api";
import { messageFor } from "@/lib/auth/messages";
import { goTo } from "@/lib/auth/navigate";

type Step = 1 | 2 | 3;

/** Claims a fresh install: the Owner account, its authenticator, then its recovery codes. */
export function SetupFlow() {
  const [step, setStep] = useState<Step>(1);
  const [codes, setCodes] = useState<string[]>([]);

  return (
    <div className="space-y-3">
      <p className="text-sm text-muted-foreground">Step {step} of 3</p>
      {step === 1 && <OwnerStep onDone={() => setStep(2)} />}
      {step === 2 && (
        <EnrolStep
          onDone={(given) => {
            if (!given) return goTo("/");
            setCodes(given);
            setStep(3);
          }}
          onRestart={() => goTo("/login")}
        />
      )}
      {step === 3 && <RecoveryCodes codes={codes} onContinue={() => goTo("/")} />}
    </div>
  );
}

/** The first step: the setup code from the host and the Owner's account. */
function OwnerStep({ onDone }: { onDone: () => void }) {
  const [code, setCode] = useState("");
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [repeat, setRepeat] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    // The backend counts code points, like the spread.
    const length = [...password].length;
    if (length < 12 || length > 128) return setError("Use 12 to 128 characters.");
    if (password !== repeat) return setError("The passwords do not match.");
    setBusy(true);
    setError(null);
    try {
      await apiFetch("/auth/setup", { body: { code: code.trim(), name, email: email.trim(), password } });
      onDone();
      return;
    } catch (e) {
      if (e instanceof ApiError && e.status === 409) return goTo("/login");
      setError(messageFor(e instanceof ApiError ? e.detail : "error"));
    }
    setBusy(false);
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>
          <h1 className="text-xl">Set up MegooITAdmin</h1>
        </CardTitle>
        <CardDescription>Create the Owner account of this installation.</CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        {error && <Alert variant="destructive">{error}</Alert>}
        <form onSubmit={submit} className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="setup-code">Setup code</Label>
            <Input
              id="setup-code"
              autoComplete="off"
              required
              aria-describedby="setup-code-hint"
              value={code}
              onChange={(e) => setCode(e.target.value)}
            />
            <p id="setup-code-hint" className="text-sm text-muted-foreground">
              Run make setup-code on the host, or look for it in the backend&apos;s log.
            </p>
          </div>
          <div className="space-y-2">
            <Label htmlFor="setup-name">Your name</Label>
            <Input
              id="setup-name"
              autoComplete="name"
              required
              value={name}
              onChange={(e) => setName(e.target.value)}
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="setup-email">Email</Label>
            <Input
              id="setup-email"
              type="email"
              autoComplete="username"
              required
              value={email}
              onChange={(e) => setEmail(e.target.value)}
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="setup-password">Password</Label>
            <Input
              id="setup-password"
              type="password"
              autoComplete="new-password"
              required
              aria-describedby="setup-password-hint"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
            />
            <p id="setup-password-hint" className="text-sm text-muted-foreground">
              12 to 128 characters.
            </p>
          </div>
          <div className="space-y-2">
            <Label htmlFor="setup-repeat">Repeat the password</Label>
            <Input
              id="setup-repeat"
              type="password"
              autoComplete="new-password"
              required
              value={repeat}
              onChange={(e) => setRepeat(e.target.value)}
            />
          </div>
          <Button type="submit" className="w-full" disabled={busy}>
            Create the Owner account
          </Button>
        </form>
      </CardContent>
    </Card>
  );
}
