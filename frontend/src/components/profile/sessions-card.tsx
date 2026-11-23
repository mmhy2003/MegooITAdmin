"use client";

import { useCallback, useEffect, useState } from "react";
import { formatTime } from "@/components/profile/profile-page";
import { Alert } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { ApiError, apiFetch } from "@/lib/api";
import { messageFor } from "@/lib/auth/messages";

/** One row of `GET /api/auth/sessions`. */
export type SessionRow = {
  id: string;
  current: boolean;
  created_at: string;
  last_seen_at: string;
  ip: string | null;
  user_agent: string | null;
  mfa_method: string | null;
};

function deviceOf(row: SessionRow): string {
  return row.user_agent ?? "Unknown device";
}

/** The browsers signed in to the account; each one but this can be signed out. */
export function SessionsCard() {
  const [rows, setRows] = useState<SessionRow[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [ending, setEnding] = useState<SessionRow | null>(null);
  const [busy, setBusy] = useState(false);
  const [refusal, setRefusal] = useState<string | null>(null);

  const reload = useCallback(
    () =>
      apiFetch<SessionRow[]>("/auth/sessions").then(
        (body) => {
          setRows(body);
          setError(null);
        },
        (e: unknown) => setError(e instanceof ApiError ? e.detail : "error"),
      ),
    [],
  );

  useEffect(() => {
    void reload();
  }, [reload]);

  function confirm(row: SessionRow) {
    setRefusal(null);
    setEnding(row);
  }

  async function signOut() {
    if (!ending) return;
    setBusy(true);
    setRefusal(null);
    try {
      await apiFetch(`/auth/sessions/${ending.id}`, { method: "DELETE" });
      setEnding(null);
      void reload();
    } catch (e) {
      setRefusal(messageFor(e instanceof ApiError ? e.detail : "error"));
    }
    setBusy(false);
  }

  return (
    <Card className="lg:col-span-2">
      <CardHeader>
        <CardTitle>
          <h2>Sessions</h2>
        </CardTitle>
        <CardDescription>Browsers signed in to your account.</CardDescription>
      </CardHeader>
      <CardContent>
        {error && <Alert variant="destructive">{messageFor(error)}</Alert>}
        {rows && (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Device</TableHead>
                <TableHead>Address</TableHead>
                <TableHead>Signed in</TableHead>
                <TableHead>Last active</TableHead>
                <TableHead>
                  <span className="sr-only">Actions</span>
                </TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {rows.map((row) => (
                <TableRow key={row.id}>
                  <TableCell className="max-w-xs truncate" title={row.user_agent ?? undefined}>
                    {deviceOf(row)}
                  </TableCell>
                  <TableCell className="font-mono">{row.ip ?? "—"}</TableCell>
                  <TableCell>{formatTime(row.created_at)}</TableCell>
                  <TableCell>{formatTime(row.last_seen_at)}</TableCell>
                  <TableCell className="text-right">
                    {row.current ? (
                      <Badge>This session</Badge>
                    ) : (
                      <Button
                        variant="ghost"
                        aria-label={`Sign out the session on ${deviceOf(row)}`}
                        onClick={() => confirm(row)}
                      >
                        Sign out
                      </Button>
                    )}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </CardContent>
      <Dialog open={ending !== null} onOpenChange={(open) => !open && setEnding(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Sign out this session?</DialogTitle>
            <DialogDescription>That browser has to sign in again.</DialogDescription>
          </DialogHeader>
          {refusal && <Alert variant="destructive">{refusal}</Alert>}
          <DialogFooter>
            <Button variant="outline" onClick={() => setEnding(null)}>
              Cancel
            </Button>
            <Button variant="destructive" disabled={busy} onClick={() => void signOut()}>
              Sign out
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </Card>
  );
}
