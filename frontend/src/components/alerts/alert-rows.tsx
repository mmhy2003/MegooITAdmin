import Link from "next/link";
import type { ReactNode } from "react";
import { AlertStateBadge } from "@/components/alerts/alert-state-badge";
import { SeverityBadge } from "@/components/alerts/severity-badge";
import { formatTime } from "@/components/profile/profile-page";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { type Alert, alertHeadline, ruleSentence } from "@/lib/alerts";

const DASH = "—";

type Props = {
  alerts: Alert[];
  /** Whether to show the Server column (not on a server's own page). */
  showServer?: boolean;
  /** What to show when there are no alerts. */
  children: ReactNode;
};

/** Alerts as a table, one row per alert, or the empty state when there is none. */
export function AlertRows({ alerts, showServer = true, children }: Props) {
  if (alerts.length === 0) return <>{children}</>;
  return (
    <div className="overflow-x-auto">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Severity</TableHead>
            {showServer && <TableHead>Server</TableHead>}
            <TableHead>What happened</TableHead>
            <TableHead>Rule</TableHead>
            <TableHead>Fired</TableHead>
            <TableHead>Resolved</TableHead>
            <TableHead>State</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {alerts.map((alert) => (
            <TableRow key={alert.id} data-alert-id={alert.id}>
              <TableCell>
                <SeverityBadge severity={alert.severity} />
              </TableCell>
              {showServer && (
                <TableCell className="font-medium">
                  <Link href={`/servers/${alert.server_id}?tab=alerts`} className="hover:underline">
                    {alert.server_name}
                  </Link>
                </TableCell>
              )}
              <TableCell>{alertHeadline(alert)}</TableCell>
              <TableCell className="text-muted-foreground">{ruleSentence(alert)}</TableCell>
              <TableCell className="tabular-nums">{formatTime(alert.fired_at)}</TableCell>
              <TableCell className="tabular-nums">
                {alert.resolved_at === null ? DASH : formatTime(alert.resolved_at)}
              </TableCell>
              <TableCell>
                <AlertStateBadge state={alert.state} />
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}
