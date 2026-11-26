import { CheckCard } from "@/components/servers/checks/check-card";
import { Badge } from "@/components/ui/badge";
import { agoText, type ServerCheck, TONE_CLASSES } from "@/lib/checks";

/** The server's pending package updates, from apt or dnf. */
export function UpdatesCard({ check, now }: { check: ServerCheck<"updates">; now: Date }) {
  const data = check.data;
  const okBadge =
    data && data.pending > 0 ? (
      <Badge variant="outline" className={TONE_CLASSES.amber}>
        Updates
      </Badge>
    ) : (
      <Badge variant="outline" className={TONE_CLASSES.green}>
        Up to date
      </Badge>
    );
  return (
    <CheckCard title="Updates" check={check} now={now} okBadge={okBadge}>
      {data && (
        <div className="space-y-2">
          <p>{data.pending > 0 ? `${data.pending} pending updates` : "Up to date"}</p>
          {data.security !== null && data.security > 0 && (
            <p className="text-amber-ink">{data.security} security updates</p>
          )}
          {data.reboot_required && (
            <Badge variant="outline" className={TONE_CLASSES.amber}>
              Restart required
            </Badge>
          )}
          {data.lists_refreshed_at !== null && (
            <p className="text-sm text-muted-foreground">
              Package lists refreshed {agoText(data.lists_refreshed_at, now)}
            </p>
          )}
        </div>
      )}
    </CheckCard>
  );
}
