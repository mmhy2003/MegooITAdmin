import { Badge } from "@/components/ui/badge";
import type { Monitoring } from "@/lib/servers";

/** Whether the collector reaches the server: always a text label, never colour alone. */
export function MonitoringBadge({ monitoring }: { monitoring: Monitoring | null }) {
  if (monitoring === null)
    return (
      <Badge variant="outline" className="border-dashed text-muted-foreground">
        Not checked yet
      </Badge>
    );
  if (monitoring.state === "reachable")
    return (
      <Badge variant="outline" className="border-green text-green-ink">
        <span aria-hidden className="size-1.5 rounded-full bg-green" />
        Reachable
      </Badge>
    );
  if (monitoring.state === "unreachable") return <Badge variant="destructive">Unreachable</Badge>;
  return (
    <Badge variant="outline" className="text-muted-foreground">
      Not monitored
    </Badge>
  );
}
