import { CheckCard } from "@/components/servers/checks/check-card";
import type { Proc, ServerCheck } from "@/lib/checks";

const MIB = 1_048_576;

function ProcessList({ label, processes }: { label: string; processes: Proc[] }) {
  return (
    <div className="space-y-1">
      <h4 className="text-sm font-medium">{label}</h4>
      <ul aria-label={label} className="space-y-1">
        {processes.map((proc) => (
          <li key={proc.pid} className="flex items-center justify-between gap-3 text-sm">
            <span className="min-w-0 truncate">
              <span className="font-medium">{proc.name}</span>{" "}
              <span className="text-muted-foreground">{proc.user}</span>{" "}
              <span className="font-mono text-muted-foreground">{proc.pid}</span>
            </span>
            <span className="shrink-0 tabular-nums">
              <span>{proc.cpu_percent.toFixed(1)}% CPU</span> ·{" "}
              <span>{(proc.memory_bytes / MIB).toFixed(1)} MiB</span>
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}

/** The busiest processes by CPU and by memory; they need the View processes right. */
export function TopProcessesCard({
  check,
  now,
  canView,
  groupName,
}: {
  check: ServerCheck<"processes">;
  now: Date;
  canView: boolean;
  groupName: string;
}) {
  if (!canView) {
    return (
      <CheckCard title="Top processes" check={check} now={now} always>
        <p>You need the View processes right in {groupName} to see processes.</p>
      </CheckCard>
    );
  }
  const data = check.data;
  return (
    <CheckCard title="Top processes" check={check} now={now}>
      {data && (
        <div className="space-y-3">
          <ProcessList label="By CPU" processes={data.by_cpu} />
          <ProcessList label="By memory" processes={data.by_memory} />
        </div>
      )}
    </CheckCard>
  );
}
