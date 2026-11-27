"use client";

import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import type { AlertRule } from "@/lib/alerts";

type Props = {
  rule?: AlertRule | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onSaved: () => void;
};

/** Creates an alert rule, or edits `rule`. */
export function AlertRuleDialog({ rule, open, onOpenChange }: Props) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{rule ? `Edit ${rule.name}` : "New alert rule"}</DialogTitle>
          <DialogDescription>A rule fires when its condition holds on a server for its whole duration.</DialogDescription>
        </DialogHeader>
      </DialogContent>
    </Dialog>
  );
}
