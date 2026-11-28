"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { useCallback, useEffect, useMemo, useState } from "react";
import { DeleteViewDialog } from "@/components/logs/delete-view-dialog";
import { LogViewer } from "@/components/logs/log-viewer";
import { SaveViewDialog } from "@/components/logs/save-view-dialog";
import { ViewsMenu } from "@/components/logs/views-menu";
import { Alert } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { ApiError, apiFetch } from "@/lib/api";
import { messageFor } from "@/lib/auth/messages";
import { queryOf, stateFrom, type ViewState } from "@/lib/logs/sources";
import { bodyOf, differs, listViews, stateOf, updateView, type LogView } from "@/lib/logs/views";
import type { Server } from "@/lib/servers";

/** What the Views menu has open: saving as a new view, renaming or sharing the current one, or deleting it. */
type Editing = "new" | "edit" | "delete" | null;

function errorOf(e: unknown): string {
  return e instanceof ApiError ? e.detail : "error";
}

/**
 * The Logs page: follows the sources and settings in the address, on the servers the person sees, and keeps them as
 * saved views. The address's `view` names the view they came from; it is dropped once that view is no longer listed.
 */
export function LogsPage() {
  const router = useRouter();
  const params = useSearchParams();
  const search = params.toString();
  // A new object only when the address changes, so the viewer's state stays the same between renders.
  const { view, state } = useMemo(() => {
    const { view, ...state } = stateFrom(new URLSearchParams(search));
    return { view, state };
  }, [search]);
  const [servers, setServers] = useState<Server[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [views, setViews] = useState<LogView[] | null>(null);
  const [viewError, setViewError] = useState<string | null>(null);
  const [editing, setEditing] = useState<Editing>(null);

  const reload = useCallback(() => {
    listViews().then(setViews, (e: unknown) => setViewError(errorOf(e)));
  }, []);

  useEffect(() => {
    apiFetch<Server[]>("/servers").then(setServers, (e: unknown) => setError(errorOf(e)));
    reload();
  }, [reload]);

  const current = (view !== null && views?.find((v) => v.id === view)) || null;

  const go = useCallback(
    (next: ViewState, id: string | null) => {
      const query = queryOf(next, id);
      router.replace(query ? `/logs?${query}` : "/logs");
    },
    [router],
  );

  // A view deleted, unshared or out of reach since: the address keeps what it shows, without the link to it.
  const lost = views !== null && view !== null && current === null;
  useEffect(() => {
    if (lost) go(state, null);
  }, [lost, go, state]);

  function change(next: ViewState) {
    go(next, view);
  }

  async function save() {
    if (!current) return;
    setViewError(null);
    try {
      await updateView(current.id, bodyOf(state, current.name, current.shared));
    } catch (e) {
      setViewError(errorOf(e));
    }
    reload();
  }

  function saved(next: LogView) {
    if (editing === "new") go(state, next.id);
    setEditing(null);
    reload();
  }

  if (error) return <Alert variant="destructive">{messageFor(error)}</Alert>;
  if (!servers) return null;
  if (!servers.some((s) => s.can_view_logs)) {
    return (
      <p className="text-muted-foreground">
        You do not hold View logs on any server. The Owner grants it in Settings → Users.
      </p>
    );
  }
  const menu = (
    <ViewsMenu views={views ?? []} current={current} changed={current !== null && differs(state, current)}
      onOpen={(v) => go(stateOf(v), v.id)} onSave={save} onSaveAs={() => setEditing("new")}
      onEdit={() => setEditing("edit")} onDelete={() => setEditing("delete")} />
  );
  return (
    <div className="flex flex-col gap-4">
      {current && (
        <div className="flex items-center gap-2">
          <h2 className="min-w-0 truncate text-xl font-semibold">{current.name}</h2>
          {differs(state, current) && <Badge variant="outline">Changed</Badge>}
        </div>
      )}
      {viewError && <Alert variant="destructive">{messageFor(viewError)}</Alert>}
      <LogViewer state={state} onChange={change} servers={servers} extra={menu} />
      <SaveViewDialog view={editing === "edit" ? current : null} state={state}
        open={editing === "new" || (editing === "edit" && current !== null)}
        onOpenChange={(open) => !open && setEditing(null)} onSaved={saved} />
      <DeleteViewDialog view={current} open={editing === "delete"} onOpenChange={(open) => !open && setEditing(null)}
        onDeleted={() => {
          setEditing(null);
          reload();
        }} />
    </div>
  );
}
