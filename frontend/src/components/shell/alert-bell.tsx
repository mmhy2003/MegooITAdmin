"use client";

import { Bell } from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { SeverityBadge } from "@/components/alerts/severity-badge";
import { formatTime } from "@/components/profile/profile-page";
import { Button } from "@/components/ui/button";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { useRefresh } from "@/hooks/use-refresh";
import { type AlertEvents, eventSentence } from "@/lib/alerts";
import { apiFetch } from "@/lib/api";

/** The count the bell shows: nothing when no event is unseen, and 99+ above 99. */
function countText(unseen: number): string | null {
  if (unseen <= 0) return null;
  return unseen > 99 ? "99+" : String(unseen);
}

/** The bell in the header: how many alert events are new, and the 10 latest of them, each a link to its server. */
export function AlertBell() {
  const [answer, setAnswer] = useState<AlertEvents | null>(null);
  const unseen = answer?.unseen ?? 0;

  useEffect(() => {
    apiFetch<AlertEvents>("/alerts/events").then(setAnswer, () => {});
  }, []);

  // A background re-read fails silently and keeps what is shown.
  const refresh = useCallback(() => {
    apiFetch<AlertEvents>("/alerts/events", { background: true }).then(setAnswer, () => {});
  }, []);
  useRefresh(refresh, true);

  function opened(open: boolean) {
    if (!open || unseen === 0) return;
    setAnswer((current) => current && { ...current, unseen: 0 });
    apiFetch("/alerts/seen", { method: "POST" }).catch(() => {});
  }

  const count = countText(unseen);
  const events = answer?.events ?? [];

  return (
    <Popover onOpenChange={opened}>
      <PopoverTrigger asChild>
        <Button variant="ghost" size="icon" aria-label={`Alerts, ${unseen} new`} className="relative">
          <Bell aria-hidden />
          {count !== null && (
            <span
              aria-hidden
              className="absolute -top-0.5 -right-0.5 min-w-4 rounded-full bg-destructive px-1 text-[10px] leading-4 font-semibold text-white tabular-nums"
            >
              {count}
            </span>
          )}
        </Button>
      </PopoverTrigger>
      <PopoverContent align="end" className="w-96 p-2" aria-label="Alert events">
        {events.length === 0 ? (
          <p className="p-2 text-sm text-muted-foreground">No alert events yet.</p>
        ) : (
          <ul className="space-y-1">
            {events.map((event) => (
              <li key={event.id}>
                <Link
                  href={`/servers/${event.alert.server_id}?tab=alerts`}
                  className="flex flex-col gap-1 rounded-sm p-2 text-sm hover:bg-accent"
                >
                  <span>{eventSentence(event)}</span>
                  <span className="flex items-center gap-2 text-xs text-muted-foreground">
                    <SeverityBadge severity={event.alert.severity} />
                    <span className="tabular-nums">{formatTime(event.at)}</span>
                  </span>
                </Link>
              </li>
            ))}
          </ul>
        )}
      </PopoverContent>
    </Popover>
  );
}
