import { formatTime } from "@/components/profile/profile-page";
import { Field } from "@/components/servers/field";
import { MonitoringBadge } from "@/components/servers/monitoring-badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { monitoringText, NOT_CHECKED } from "@/lib/auth/messages";
import type { Server } from "@/lib/servers";

/** Whether the collector reaches the server, since when, and why not. */
export function MonitoringCard({ server }: { server: Server }) {
  const m = server.monitoring;
  const text = m === null ? NOT_CHECKED : monitoringText(m.reason);
  return (
    <Card>
      <CardHeader>
        <CardTitle>
          <h3>Monitoring</h3>
        </CardTitle>
      </CardHeader>
      <CardContent>
        <dl className="space-y-3">
          <Field label="Status">
            <MonitoringBadge monitoring={m} />
          </Field>
          {m !== null && <Field label="Since">{formatTime(m.since)}</Field>}
          {m?.state === "unreachable" && (
            <Field label="Last sample">
              {m.last_sample_at ? formatTime(m.last_sample_at) : <span className="text-muted-foreground">None yet</span>}
            </Field>
          )}
          {server.os === "linux" && (
            <Field label="Sample interval">{intervalText(server.metrics_interval_seconds)}</Field>
          )}
        </dl>
        {text && (
          <div data-testid="monitoring-reason" className="mt-4 space-y-1">
            <p className="font-medium">{text.title}</p>
            {text.advice && <p className="text-sm text-muted-foreground">{text.advice}</p>}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function intervalText(seconds: number) {
  return seconds === 1 ? "Every second" : `Every ${seconds} seconds`;
}
