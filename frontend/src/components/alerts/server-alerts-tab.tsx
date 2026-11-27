"use client";

import { useState } from "react";
import { AlertRows } from "@/components/alerts/alert-rows";
import { Alert as Notice } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { type Alert, afterAlert } from "@/lib/alerts";
import { ApiError, apiFetch } from "@/lib/api";
import { messageFor } from "@/lib/auth/messages";

/** How many closed alerts one page of GET /api/servers/{id}/alerts holds. */
const PAGE = 50;

type Older = { alerts: Alert[]; more: boolean };

/**
 * A server's Alerts tab. `alerts` is the answer of GET /api/servers/{id}/alerts: the firing ones, then the first page of
 * the closed ones; "Show more" reads the next pages.
 */
export function ServerAlertsTab({ serverId, alerts }: { serverId: string; alerts: Alert[] }) {
  const [older, setOlder] = useState<Older | null>(null);
  const [error, setError] = useState<string | null>(null);
  // Whether the next page is being read, so "Show more" asks only once.
  const [loading, setLoading] = useState(false);

  const firing = alerts.filter((alert) => alert.state === "firing");
  const first = alerts.filter((alert) => alert.state !== "firing");
  const shown = new Set(first.map((alert) => alert.id));
  const history = [...first, ...(older?.alerts ?? []).filter((alert) => !shown.has(alert.id))];
  const more = older === null ? first.length === PAGE : older.more;
  const last = history.at(-1);

  function showMore(after: Alert) {
    setLoading(true);
    apiFetch<Alert[]>(`/servers/${serverId}/alerts?${new URLSearchParams(afterAlert(after))}`).then(
      (page) => {
        setOlder((current) => ({ alerts: [...(current?.alerts ?? []), ...page], more: page.length === PAGE }));
        setError(null);
        setLoading(false);
      },
      (e: unknown) => {
        setError(e instanceof ApiError ? e.detail : "error");
        setLoading(false);
      },
    );
  }

  return (
    <>
      <Card role="region" aria-labelledby="server-alerts-firing">
        <CardHeader>
          <CardTitle>
            <h3 id="server-alerts-firing">Firing</h3>
          </CardTitle>
        </CardHeader>
        <CardContent>
          <AlertRows alerts={firing} showServer={false}>
            <p className="text-muted-foreground">No alerts are firing.</p>
          </AlertRows>
        </CardContent>
      </Card>
      <Card role="region" aria-labelledby="server-alerts-history">
        <CardHeader>
          <CardTitle>
            <h3 id="server-alerts-history">History</h3>
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <AlertRows alerts={history} showServer={false}>
            <p className="text-muted-foreground">No alert has closed on this server yet.</p>
          </AlertRows>
          {error && <Notice variant="destructive">{messageFor(error)}</Notice>}
          {more && last?.resolved_at && (
            <Button variant="outline" disabled={loading} onClick={() => showMore(last)}>
              Show more
            </Button>
          )}
        </CardContent>
      </Card>
    </>
  );
}
