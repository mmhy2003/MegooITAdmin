"use client";

import { useState, type FormEvent } from "react";
import { AccessForm } from "@/components/settings/access-form";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import type { AccessValue, InviteLink, ServerGroup } from "@/lib/access";
import { ApiError, apiFetch } from "@/lib/api";
import { messageFor } from "@/lib/auth/messages";

type Props = {
  groups: ServerGroup[];
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onCreated: (link: InviteLink, name: string) => void;
};

/** Creates an account for a person, with their access, and an invite link for them. */
export function InviteDialog({ groups, open, onOpenChange, onCreated }: Props) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-3xl">
        {/* The form unmounts when the dialog closes, so the next invite starts empty. */}
        <InviteForm groups={groups} onCreated={onCreated} />
      </DialogContent>
    </Dialog>
  );
}

function InviteForm({ groups, onCreated }: Pick<Props, "groups" | "onCreated">) {
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [access, setAccess] = useState<AccessValue>({ platform_role: null, grants: [] });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const link = await apiFetch<InviteLink>("/users", {
        method: "POST",
        body: { name, email, platform_role: access.platform_role, grants: access.grants },
      });
      onCreated(link, name);
    } catch (e) {
      setError(messageFor(e instanceof ApiError ? e.detail : "error"));
    }
    setBusy(false);
  }

  return (
    <>
      <DialogHeader>
        <DialogTitle>Invite a person</DialogTitle>
        <DialogDescription>They get a link to choose their password and set up two-step verification.</DialogDescription>
      </DialogHeader>
      <form onSubmit={submit} className="grid max-h-[70vh] gap-4 overflow-y-auto">
        {error && <Alert variant="destructive">{error}</Alert>}
        <div className="grid gap-4 sm:grid-cols-2">
          <div className="space-y-2">
            <Label htmlFor="invite-name">Name</Label>
            <Input id="invite-name" required maxLength={200} value={name} onChange={(e) => setName(e.target.value)} />
          </div>
          <div className="space-y-2">
            <Label htmlFor="invite-email">Email</Label>
            <Input
              id="invite-email"
              type="email"
              required
              value={email}
              onChange={(e) => setEmail(e.target.value)}
            />
          </div>
        </div>
        <AccessForm value={access} groups={groups} onChange={setAccess} />
        <DialogFooter>
          <Button type="submit" disabled={busy}>
            Create invite link
          </Button>
        </DialogFooter>
      </form>
    </>
  );
}
