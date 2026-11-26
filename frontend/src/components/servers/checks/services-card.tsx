import { CheckCard } from "@/components/servers/checks/check-card";
import { Badge } from "@/components/ui/badge";
import { type ServerCheck, TONE_CLASSES } from "@/lib/checks";

/** The server's systemd units: how many run, and which failed. */
export function ServicesCard({ check, now }: { check: ServerCheck<"services">; now: Date }) {
  const data = check.data;
  const okBadge =
    data && data.failed > 0 ? (
      <Badge variant="outline" className={TONE_CLASSES.pink}>
        {data.failed} failed
      </Badge>
    ) : (
      <Badge variant="outline" className={TONE_CLASSES.green}>
        All running
      </Badge>
    );
  return (
    <CheckCard title="Services" check={check} now={now} okBadge={okBadge}>
      {data && (
        <>
          <p>
            {data.running} running · {data.failed} failed · {data.total} in all
          </p>
          {data.failed_units.length === 0 ? (
            <p className="text-sm text-muted-foreground">No failed services.</p>
          ) : (
            <ul className="space-y-2">
              {data.failed_units.map((unit) => (
                <li key={unit.unit} className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <p className="truncate font-mono text-sm">{unit.unit}</p>
                    <p className="text-sm text-muted-foreground">{unit.description}</p>
                  </div>
                  <Badge variant="outline" className={TONE_CLASSES.pink}>
                    Failed
                  </Badge>
                </li>
              ))}
            </ul>
          )}
        </>
      )}
    </CheckCard>
  );
}
