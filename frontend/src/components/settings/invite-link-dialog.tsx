"use client";

import { useState } from "react";
import { formatTime } from "@/components/profile/profile-page";
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
import { type InviteLink, inviteLink } from "@/lib/access";

type Props = {
  link: InviteLink | null;
  name: string;
  onDone: () => void;
};

/** Shows a new invite link once, to copy and pass on; it is open while there is a link. */
export function InviteLinkDialog({ link, name, onDone }: Props) {
  return (
    <Dialog open={link !== null} onOpenChange={(open) => !open && onDone()}>
      <DialogContent>{link && <LinkOnce link={link} name={name} onDone={onDone} />}</DialogContent>
    </Dialog>
  );
}

function LinkOnce({ link, name, onDone }: { link: InviteLink; name: string; onDone: () => void }) {
  const [copied, setCopied] = useState(false);
  const url = inviteLink(window.location.origin, link.token);

  async function copy() {
    await navigator.clipboard.writeText(url);
    setCopied(true);
  }

  return (
    <>
      <DialogHeader>
        <DialogTitle>Invite link for {name}</DialogTitle>
        <DialogDescription>
          This link is shown once. It works until {formatTime(link.expires_at)}.
        </DialogDescription>
      </DialogHeader>
      <div className="space-y-2">
        <Label htmlFor="invite-link">Invite link</Label>
        <div className="flex gap-2">
          <Input id="invite-link" readOnly value={url} className="font-mono" onFocus={(e) => e.target.select()} />
          <Button variant="outline" onClick={() => void copy()}>
            {copied ? "Copied" : "Copy link"}
          </Button>
        </div>
      </div>
      <DialogFooter>
        <Button onClick={onDone}>Done</Button>
      </DialogFooter>
    </>
  );
}
