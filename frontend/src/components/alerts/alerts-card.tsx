"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { AlertRows } from "@/components/alerts/alert-rows";
import { Alert as Notice } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { type Alert, alertsPath } from "@/lib/alerts";
import { ApiError, apiFetch } from "@/lib/api";
import { messageFor } from "@/lib/auth/messages";
import type { ServerFilters } from "@/lib/servers";

/** How many closed alerts one page of GET /api/alerts holds. */
const PAGE = 50;

const TAB_CLASSES = {
  selected: "-mb-px border-b-2 border-primary px-3 py-2 text-sm font-semibold",
  other: "-mb-px border-b-2 border-transparent px-3 py-2 text-sm text-muted-foreground hover:text-foreground",
};

type Tab = "firing" | "history";
type History = { alerts: Alert[]; more: boolean };

type Props = { firing: Alert[]; filters: ServerFilters };

/** The Dashboard's alerts: those firing now, and the history of the closed ones, both of the filtered servers. */
export function AlertsCard({ firing, filters }: Props) {
  const [tab, setTab] = useState<Tab>("firing");
  const [history, setHistory] = useState<History | null>(null);
  const [error, setError] = useState<string | null>(null);
  // Whether the next page is being read, so "Show more" asks only once.
  const [loading, setLoading] = useState(false);
  const path = alertsPath("closed", filters);
  // Each read takes a number; an answer is applied only while its read is still the latest.
  const reads = useRef(0);

  // Reads one page: the first, which replaces what is shown, or the next, which is added below it.
  const read = useCallback((target: string, next: boolean) => {
    const number = ++reads.current;
    apiFetch<Alert[]>(target).then(
      (page) => {
        if (number !== reads.current) return;
        setHistory((current) => ({
          alerts: next && current !== null ? [...current.alerts, ...page] : page,
          more: page.length === PAGE,
        }));
        setError(null);
        setLoading(false);
      },
      (e: unknown) => {
        if (number !== reads.current) return;
        setError(e instanceof ApiError ? e.detail : "error");
        setLoading(false);
      },
    );
  }, []);

  // The history is read when it is opened, and again when the filters change while it is open.
  useEffect(() => {
    if (tab === "history") read(path, false);
  }, [tab, path, read]);

  const last = history?.alerts.at(-1)?.resolved_at;

  return (
    <Card>
      <CardHeader>
        <CardTitle>
          <h2>Alerts</h2>
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        <div role="tablist" aria-label="Alerts" className="flex gap-2 border-b">
          <TabButton tab="firing" current={tab} onSelect={setTab}>
            {`Firing (${firing.length})`}
          </TabButton>
          <TabButton tab="history" current={tab} onSelect={setTab}>
            History
          </TabButton>
        </div>
        <div role="tabpanel" id="alerts-tab-panel" aria-labelledby={`alerts-tab-${tab}`} className="space-y-4">
          {tab === "firing" ? (
            <AlertRows alerts={firing}>
              <p className="text-muted-foreground">No alerts are firing.</p>
            </AlertRows>
          ) : (
            <>
              {error && <Notice variant="destructive">{messageFor(error)}</Notice>}
              {history && (
                <AlertRows alerts={history.alerts}>
                  <p className="text-muted-foreground">No alerts in the last 30 days.</p>
                </AlertRows>
              )}
              {history?.more && last && (
                <Button
                  variant="outline"
                  disabled={loading}
                  onClick={() => {
                    setLoading(true);
                    read(alertsPath("closed", filters, last), true);
                  }}
                >
                  Show more
                </Button>
              )}
            </>
          )}
        </div>
      </CardContent>
    </Card>
  );
}

function TabButton({
  tab,
  current,
  onSelect,
  children,
}: {
  tab: Tab;
  current: Tab;
  onSelect: (tab: Tab) => void;
  children: string;
}) {
  return (
    <button
      type="button"
      role="tab"
      id={`alerts-tab-${tab}`}
      aria-selected={tab === current}
      aria-controls="alerts-tab-panel"
      className={tab === current ? TAB_CLASSES.selected : TAB_CLASSES.other}
      onClick={() => onSelect(tab)}
    >
      {children}
    </button>
  );
}
