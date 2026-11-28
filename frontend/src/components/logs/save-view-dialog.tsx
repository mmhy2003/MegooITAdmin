"use client";

import { useId, useState, type FormEvent } from "react";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import {
  Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { ApiError } from "@/lib/api";
import { messageFor } from "@/lib/auth/messages";
import type { ViewState } from "@/lib/logs/sources";
import { bodyOf, createView, MAX_VIEW_NAME, stateOf, updateView, type LogView } from "@/lib/logs/views";

type Props = {
  /** The view to rename or share; null saves `state` as a new view. */
  view: LogView | null;
  state: ViewState;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onSaved: (saved: LogView) => void;
};

/** Saves what the viewer shows as a new view, or renames or shares a saved one without changing what it shows. */
export function SaveViewDialog({ view, state, open, onOpenChange, onSaved }: Props) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        {/* Keyed by the view, and unmounted when closed, so the form always starts from the saved view. */}
        <SaveViewForm key={view?.id ?? "new"} view={view} state={state} onSaved={onSaved} />
      </DialogContent>
    </Dialog>
  );
}

function SaveViewForm({ view, state, onSaved }: { view: LogView | null; state: ViewState;
  onSaved: (saved: LogView) => void }) {
  const id = useId();
  const [name, setName] = useState(view?.name ?? "");
  const [shared, setShared] = useState(view?.shared ?? false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const trimmed = name.trim();
    if (trimmed === "") {
      setError("Give the view a name.");
      return;
    }
    if (trimmed.length > MAX_VIEW_NAME) {
      setError(`A name has at most ${MAX_VIEW_NAME} characters.`);
      return;
    }
    setBusy(true);
    setError(null);
    try {
      onSaved(view
        ? await updateView(view.id, bodyOf(stateOf(view), trimmed, shared))
        : await createView(bodyOf(state, trimmed, shared)));
    } catch (e) {
      setError(messageFor(e instanceof ApiError ? e.detail : "error"));
    }
    setBusy(false);
  }

  return (
    <>
      <DialogHeader>
        <DialogTitle>{view ? `Rename or share ${view.name}` : "Save as a new view"}</DialogTitle>
        <DialogDescription>
          {view ? "What the view shows stays as it was saved." : "A view keeps the sources, the filter and the settings."}
        </DialogDescription>
      </DialogHeader>
      <form onSubmit={submit} className="grid gap-4">
        {error && <Alert variant="destructive">{error}</Alert>}
        <div className="space-y-2">
          <Label htmlFor={`${id}-name`}>Name</Label>
          <Input id={`${id}-name`} required value={name} onChange={(e) => setName(e.target.value)} />
        </div>
        <div className="space-y-2">
          <div className="flex items-center gap-2">
            <Checkbox id={`${id}-shared`} aria-describedby={`${id}-shared-hint`} checked={shared}
              onCheckedChange={(on) => setShared(on === true)} />
            <Label htmlFor={`${id}-shared`} className="font-normal">Shared</Label>
          </div>
          <p id={`${id}-shared-hint`} className="text-sm text-muted-foreground">
            People who hold View logs on every server of this view see it.
          </p>
        </div>
        <DialogFooter>
          <Button type="submit" disabled={busy}>{view ? "Save" : "Save view"}</Button>
        </DialogFooter>
      </form>
    </>
  );
}
