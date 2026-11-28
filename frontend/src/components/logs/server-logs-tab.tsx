"use client";

import { ExternalLinkIcon } from "lucide-react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useMemo } from "react";
import { LogViewer } from "@/components/logs/log-viewer";
import { Button } from "@/components/ui/button";
import { queryOf, stateFrom, type ViewState } from "@/lib/logs/sources";
import type { Server } from "@/lib/servers";

/**
 * A server's Logs tab: the viewer for the sources of this server in the address, which keeps `tab=logs` with each
 * change. It saves no views; "Open in Logs" carries what it shows to the Logs page, which does.
 */
export function ServerLogsTab({ server }: { server: Server }) {
  const router = useRouter();
  const search = useSearchParams().toString();
  // A new object only when the address changes, so the viewer's state stays the same between renders.
  const state = useMemo<ViewState>(() => {
    const { sources, settings } = stateFrom(new URLSearchParams(search));
    return { sources: sources.filter((s) => s.server_id === server.id), settings };
  }, [search, server.id]);
  const servers = useMemo(() => [server], [server]);
  const query = queryOf(state);

  function change(next: ViewState) {
    const query = queryOf(next);
    router.replace(`/servers/${server.id}?tab=logs` + (query ? `&${query}` : ""));
  }

  const open = (
    <Button size="sm" variant="outline" asChild>
      <Link href={query ? `/logs?${query}` : "/logs"}>
        <ExternalLinkIcon />
        Open in Logs
      </Link>
    </Button>
  );
  return <LogViewer state={state} onChange={change} servers={servers} serverId={server.id} extra={open} />;
}

export default ServerLogsTab;
