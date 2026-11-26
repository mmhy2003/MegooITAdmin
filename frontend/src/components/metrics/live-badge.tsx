import { Badge } from "@/components/ui/badge";
import type { LiveStatus } from "@/lib/live-socket";

const LABELS: Record<LiveStatus, string> = {
  connecting: "Connecting…",
  live: "Live",
  reconnecting: "Reconnecting…",
  paused: "Paused",
};

/** The state of the live socket, announced politely when it changes. */
export function LiveBadge({ status }: { status: LiveStatus }) {
  return (
    <Badge
      role="status"
      variant="outline"
      className={status === "live" ? "border-cyan text-cyan-ink" : "text-muted-foreground"}
    >
      {status === "live" && <span aria-hidden className="size-1.5 rounded-full bg-cyan" />}
      {LABELS[status]}
    </Badge>
  );
}
