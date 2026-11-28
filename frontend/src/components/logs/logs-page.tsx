"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { useEffect, useMemo, useState } from "react";
import { LogViewer } from "@/components/logs/log-viewer";
import { Alert } from "@/components/ui/alert";
import { ApiError, apiFetch } from "@/lib/api";
import { messageFor } from "@/lib/auth/messages";
import { queryOf, stateFrom, type ViewState } from "@/lib/logs/sources";
import type { Server } from "@/lib/servers";

/** The Logs page: follows the sources and settings in the address, on the servers the person sees. */
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

  useEffect(() => {
    apiFetch<Server[]>("/servers").then(setServers, (e: unknown) =>
      setError(e instanceof ApiError ? e.detail : "error"),
    );
  }, []);

  function change(next: ViewState) {
    const query = queryOf(next, view);
    router.replace(query ? `/logs?${query}` : "/logs");
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
  return <LogViewer state={state} onChange={change} servers={servers} />;
}
