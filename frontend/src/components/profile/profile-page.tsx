"use client";

import { useCallback, useEffect, useState } from "react";
import { PasswordDialog } from "@/components/profile/password-dialog";
import { Alert } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { ApiError, apiFetch } from "@/lib/api";
import type { SessionUser } from "@/lib/auth/gate";
import { messageFor } from "@/lib/auth/messages";

/** What `GET /api/auth/me` answers. */
export type Me = {
  user: SessionUser;
  password_changed_at: string;
  totp_confirmed_at: string | null;
  recovery_codes_left: number;
};

const TIME_FORMAT = new Intl.DateTimeFormat("en-GB", { dateStyle: "medium", timeStyle: "short" });

/** A time from the API, for people. */
export function formatTime(iso: string): string {
  return TIME_FORMAT.format(new Date(iso));
}

/** The Profile and security page: the account and its password. */
export function ProfilePage() {
  const [me, setMe] = useState<Me | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [passwordOpen, setPasswordOpen] = useState(false);

  const reload = useCallback(
    () =>
      apiFetch<Me>("/auth/me").then(
        (body) => {
          setMe(body);
          setError(null);
        },
        (e: unknown) => setError(e instanceof ApiError ? e.detail : "error"),
      ),
    [],
  );

  useEffect(() => {
    void reload();
  }, [reload]);

  function passwordChanged() {
    setPasswordOpen(false);
    setNotice("Password changed. Your other sessions were signed out.");
    void reload();
  }

  return (
    <div className="space-y-6">
      {error && <Alert variant="destructive">{messageFor(error)}</Alert>}
      {notice && <Alert>{notice}</Alert>}
      {me && (
        <div className="grid gap-6 lg:grid-cols-2">
          <Card>
            <CardHeader>
              <CardTitle>
                <h2>Account</h2>
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-1">
              <div className="flex items-center gap-2">
                <span className="font-medium">{me.user.name}</span>
                {me.user.is_owner && <Badge>Owner</Badge>}
              </div>
              <p className="text-sm text-muted-foreground">{me.user.email}</p>
            </CardContent>
          </Card>
          <Card>
            <CardHeader>
              <CardTitle>
                <h2>Password</h2>
              </CardTitle>
              <CardDescription>Last changed {formatTime(me.password_changed_at)}</CardDescription>
            </CardHeader>
            <CardContent>
              <Button variant="outline" onClick={() => setPasswordOpen(true)}>
                Change password
              </Button>
            </CardContent>
          </Card>
        </div>
      )}
      <PasswordDialog open={passwordOpen} onOpenChange={setPasswordOpen} onChanged={passwordChanged} />
    </div>
  );
}
