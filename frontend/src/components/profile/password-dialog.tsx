"use client";

import { useState, type FormEvent } from "react";
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
  onChanged: () => void;
};

/** Changes the password; the current one proves it is the owner of the account. */
export function PasswordDialog({ open, onOpenChange, onChanged }: Props) {
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [repeat, setRepeat] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    if (next.length < 12 || next.length > 128) {
      setError("Use 12 to 128 characters.");
      return;
    }
    if (next !== repeat) {
      setError("The passwords do not match.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await apiFetch("/auth/password", {
        method: "POST",
        body: { current_password: current, new_password: next },
      });
      setCurrent("");
      setNext("");
      setRepeat("");
      onChanged();
    } catch (e) {
      setError(messageFor(e instanceof ApiError ? e.detail : "error"));
    }
    setBusy(false);
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Change password</DialogTitle>
          <DialogDescription>Your other sessions are signed out when the password changes.</DialogDescription>
        </DialogHeader>
        {error && <Alert variant="destructive">{error}</Alert>}
        <form onSubmit={submit} className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="password-current">Current password</Label>
            <Input
              id="password-current"
              type="password"
              autoComplete="current-password"
              required
              value={current}
              onChange={(e) => setCurrent(e.target.value)}
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="password-new">New password</Label>
            <Input
              id="password-new"
              type="password"
              autoComplete="new-password"
              required
              value={next}
              onChange={(e) => setNext(e.target.value)}
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="password-repeat">Repeat the new password</Label>
            <Input
              id="password-repeat"
              type="password"
              autoComplete="new-password"
              required
              value={repeat}
              onChange={(e) => setRepeat(e.target.value)}
            />
          </div>
          <Button type="submit" className="w-full" disabled={busy}>
            Change password
          </Button>
        </form>
      </DialogContent>
    </Dialog>
  );
}
