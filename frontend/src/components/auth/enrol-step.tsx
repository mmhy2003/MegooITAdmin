"use client";

import { useCallback, useEffect, useRef, useState, type FormEvent } from "react";
import { QRCodeSVG } from "qrcode.react";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { ApiError, apiFetch } from "@/lib/api";
import { messageFor } from "@/lib/auth/messages";

/** A started enrolment: the TOTP secret and its `otpauth://` address. */
export type Enrolment = { secret: string; uri: string };

type Props = {
  enrolment?: Enrolment;
  onDone: (codes: string[] | null) => void;
  onRestart: (notice: string) => void;
};

/** Registers an authenticator: shows its QR code and key, then confirms the first code. */
export function EnrolStep({ enrolment: given, onDone, onRestart }: Props) {
  const [enrolment, setEnrolment] = useState<Enrolment | null>(given ?? null);
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const started = useRef(false);

  const start = useCallback(async () => {
    setBusy(true);
    setError(null);
    try {
      setEnrolment(await apiFetch<Enrolment>("/auth/mfa/enrol", { method: "POST", body: {} }));
    } catch (e) {
      const detail = e instanceof ApiError ? e.detail : "error";
      if (detail === "not_signed_in") return onRestart(messageFor("not_signed_in"));
      setError(detail);
    }
    setBusy(false);
  }, [onRestart]);

  useEffect(() => {
    // Strict mode runs effects twice: start one enrolment only.
    if (given || started.current) return;
    started.current = true;
    void start();
  }, [given, start]);

  async function submit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const body = await apiFetch<{ recovery_codes: string[] | null }>("/auth/mfa/enrol/confirm", {
        body: { code },
      });
      onDone(body.recovery_codes);
      return;
    } catch (e) {
      const detail = e instanceof ApiError ? e.detail : "error";
      if (detail === "not_signed_in") return onRestart(messageFor("not_signed_in"));
      setError(detail);
    }
    setBusy(false);
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>
          <h1 className="text-xl">Set up your authenticator</h1>
        </CardTitle>
        <CardDescription>
          Scan the QR code with an authenticator app, then enter the 6-digit code it shows.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        {error && <Alert variant="destructive">{messageFor(error)}</Alert>}
        {!enrolment && error && (
          <Button type="button" className="w-full" disabled={busy} onClick={() => void start()}>
            Try again
          </Button>
        )}
        {enrolment && (
          <>
            <div className="flex justify-center">
              <div className="rounded-lg bg-white p-3">
                <QRCodeSVG value={enrolment.uri} size={176} title="QR code for your authenticator" />
              </div>
            </div>
            <div className="space-y-1 text-sm">
              <p className="text-muted-foreground">Can&apos;t scan it? Enter this key:</p>
              <p className="font-mono break-all">{groupsOf4(enrolment.secret)}</p>
            </div>
            <form onSubmit={submit} className="space-y-4">
              <div className="space-y-2">
                <Label htmlFor="enrol-code">Code</Label>
                <Input
                  id="enrol-code"
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
          </>
        )}
      </CardContent>
    </Card>
  );
}

function groupsOf4(secret: string): string {
  return secret.match(/.{1,4}/g)?.join(" ") ?? "";
}
