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
  onDone: (status: "mfa_required" | "enrolment_required") => void;
  notice?: string;
};

/** The first sign-in step: the email and the password. */
export function PasswordStep({ onDone, notice }: Props) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const body = await apiFetch<{ status: "mfa_required" | "enrolment_required" }>("/auth/login", {
        body: { email: email.trim(), password },
      });
      onDone(body.status);
    } catch (e) {
      setError(e instanceof ApiError ? e.detail : "error");
      setBusy(false);
    }
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>
          <h1 className="text-xl">Sign in</h1>
        </CardTitle>
        <CardDescription>Sign in with your email and your password.</CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        {notice && <p className="text-sm">{notice}</p>}
        {error && <Alert variant="destructive">{messageFor(error)}</Alert>}
        <form onSubmit={submit} className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="login-email">Email</Label>
            <Input
              id="login-email"
              type="email"
              autoComplete="username"
              required
              value={email}
              onChange={(e) => setEmail(e.target.value)}
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="login-password">Password</Label>
            <Input
              id="login-password"
              type="password"
              autoComplete="current-password"
              required
              value={password}
              onChange={(e) => setPassword(e.target.value)}
            />
          </div>
          <Button type="submit" className="w-full" disabled={busy}>
            Continue
          </Button>
        </form>
      </CardContent>
    </Card>
  );
}
