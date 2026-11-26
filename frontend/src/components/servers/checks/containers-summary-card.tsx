import Link from "next/link";
import { CheckCard } from "@/components/servers/checks/check-card";
import { Badge } from "@/components/ui/badge";
import { type ServerCheck, TONE_CLASSES } from "@/lib/checks";

/** How many of the server's containers run, with a link to the Containers tab. */
export function ContainersSummaryCard({
  check,
  now,
  href,
}: {
  check: ServerCheck<"containers">;
  now: Date;
  href: string;
}) {
  const data = check.data;
  const okBadge =
    data && data.total > 0 ? (
      <Badge variant="outline" className={TONE_CLASSES.green}>
        {data.running} running
      </Badge>
    ) : (
      <Badge variant="outline" className={TONE_CLASSES.muted}>
        None
      </Badge>
    );
  return (
    <CheckCard title="Containers" check={check} now={now} okBadge={okBadge} always>
      {data && (
        <p>
          {data.running} running · {data.not_running} not running
        </p>
      )}
      <Link href={href} className="text-sm text-primary underline-offset-4 hover:underline">
        Show containers
      </Link>
    </CheckCard>
  );
}
