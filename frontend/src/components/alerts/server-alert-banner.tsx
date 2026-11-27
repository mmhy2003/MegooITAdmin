import Link from "next/link";
import { SeverityBadge } from "@/components/alerts/severity-badge";
import { Alert as Notice, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { type Alert, alertHeadline } from "@/lib/alerts";

type Props = { serverId: string; alerts: Alert[] };

/** Above a server's tabs while alerts fire on it: each firing alert, and a link to its Alerts tab. */
export function ServerAlertBanner({ serverId, alerts }: Props) {
  if (alerts.length === 0) return null;
  return (
    <Notice variant="destructive">
      <AlertTitle>{alerts.length === 1 ? "1 alert firing" : `${alerts.length} alerts firing`}</AlertTitle>
      <AlertDescription>
        <ul className="space-y-1">
          {alerts.map((alert) => (
            <li key={alert.id} className="flex flex-wrap items-center gap-2">
              <SeverityBadge severity={alert.severity} />
              <span>{alertHeadline(alert)}</span>
            </li>
          ))}
        </ul>
        <Link href={`/servers/${serverId}?tab=alerts`} className="font-medium underline-offset-4 hover:underline">
          Show alerts
        </Link>
      </AlertDescription>
    </Notice>
  );
}
