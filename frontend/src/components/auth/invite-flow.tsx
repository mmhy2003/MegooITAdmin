"use client";

import { useEffect, useRef, useState, type FormEvent } from "react";
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
type Invitee = { name: string; email: string };
type Link = { state: "checking" } | { state: "dead" } | { state: "valid"; token: string; invitee: Invitee };

/** Accepts an invite: the token from the address's `#`, a password, the authenticator, then the recovery codes. */
export function InviteFlow() {
  const [step, setStep] = useState<Step>(1);
  const [link, setLink] = useState<Link>({ state: "checking" });
  const [codes, setCodes] = useState<string[]>([]);
  const checked = useRef(false);

  useEffect(() => {
    // Strict mode runs effects twice: check the link once.
    if (checked.current) return;
    checked.current = true;
    const token = window.location.hash.slice(1);
    // A link without a token is dead without asking.
    const check = token
      ? apiFetch<Invitee>("/auth/invite/check", { body: { token } })
      : Promise.reject(new Error("no token"));
    check.then(
      (invitee) => setLink({ state: "valid", token, invitee }),
      () => setLink({ state: "dead" }),
    );
  }, []);

  return (
    <div className="space-y-3">
      <p className="text-sm text-muted-foreground">Step {step} of 3</p>
      {step === 1 && link.state === "checking" && (
        <p role="status" className="text-sm text-muted-foreground">
          Checking the invite link…
        </p>
      )}
      {step === 1 && link.state === "dead" && <DeadLink />}
      {step === 1 && link.state === "valid" && (
        <PasswordForm token={link.token} invitee={link.invitee} onDone={() => setStep(2)} />
      )}
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

function DeadLink() {
  return (
    <Card>
      <CardHeader>
        <CardTitle>
          <h1 className="text-xl">This invite link does not work</h1>
        </CardTitle>
        <CardDescription>Ask the Owner for a new link.</CardDescription>
      </CardHeader>
    </Card>
  );
}

/** The first step: the invited person chooses their password. */
function PasswordForm({ token, invitee, onDone }: { token: string; invitee: Invitee; onDone: () => void }) {
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
      await apiFetch("/auth/invite/accept", { body: { token, password } });
      // The link is used: keep the token out of the history.
      window.history.replaceState(null, "", "/invite");
      onDone();
      return;
    } catch (e) {
      setError(messageFor(e instanceof ApiError ? e.detail : "error"));
    }
    setBusy(false);
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>
          <h1 className="text-xl">Welcome, {invitee.name}</h1>
        </CardTitle>
        <CardDescription>{invitee.email}</CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        {error && <Alert variant="destructive">{error}</Alert>}
        <form onSubmit={submit} className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="invite-password">Password</Label>
            <Input
              id="invite-password"
              type="password"
              autoComplete="new-password"
              required
              aria-describedby="invite-password-hint"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
            />
            <p id="invite-password-hint" className="text-sm text-muted-foreground">
              12 to 128 characters.
            </p>
          </div>
          <div className="space-y-2">
            <Label htmlFor="invite-repeat">Repeat the password</Label>
            <Input
              id="invite-repeat"
              type="password"
              autoComplete="new-password"
              required
              value={repeat}
              onChange={(e) => setRepeat(e.target.value)}
            />
          </div>
          <Button type="submit" className="w-full" disabled={busy}>
            Set password
          </Button>
        </form>
      </CardContent>
    </Card>
  );
}

/** An invite opened in a signed-in browser: sign out first, so nobody keeps another session by accident. */
export function InviteSignedIn({ name, email }: { name: string; email: string }) {
  const [busy, setBusy] = useState(false);

  async function signOut() {
    setBusy(true);
    await apiFetch("/auth/logout", { body: {} }).catch(() => undefined);
    // A reload keeps the `#` and its token.
    window.location.reload();
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>
          <h1 className="text-xl">Accept your invite</h1>
        </CardTitle>
        <CardDescription>
          You are signed in as {name} ({email}). Sign out first to use this invite link.
        </CardDescription>
      </CardHeader>
      <CardContent>
        <Button type="button" className="w-full" disabled={busy} onClick={signOut}>
          Sign out
        </Button>
      </CardContent>
    </Card>
  );
}
