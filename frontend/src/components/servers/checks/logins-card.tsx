import { CheckCard } from "@/components/servers/checks/check-card";
import { Badge } from "@/components/ui/badge";
import { type ServerCheck, TONE_CLASSES } from "@/lib/checks";

const FOOTNOTE = "Counts failed passwords and unknown accounts. Names that were tried are not kept.";

/** Failed SSH sign-ins of the last 24 hours, and where most of them came from. */
export function LoginsCard({ check, now }: { check: ServerCheck<"logins">; now: Date }) {
  const data = check.data;
  const okBadge =
    data && data.failed_24h > 0 ? (
      <Badge variant="outline" className={TONE_CLASSES.amber}>
        {data.failed_24h} failed
      </Badge>
    ) : (
      <Badge variant="outline" className={TONE_CLASSES.green}>
        None
      </Badge>
    );
  return (
    <CheckCard title="Failed sign-ins" check={check} now={now} okBadge={okBadge} footnote={FOOTNOTE}>
      {data && (
        <div className="space-y-2">
          <p>
            {data.failed_24h > 0
              ? `${data.failed_24h} failed SSH sign-ins in the last 24 hours`
              : "No failed SSH sign-ins in the last 24 hours"}
          </p>
          {data.top_sources.length > 0 && (
            <ul className="space-y-1">
              {data.top_sources.map((source) => (
                <li key={source.address} className="flex items-center justify-between gap-3 text-sm">
                  <span className="font-mono">{source.address}</span>
                  <span className="text-muted-foreground">{source.count} attempts</span>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </CheckCard>
  );
}
