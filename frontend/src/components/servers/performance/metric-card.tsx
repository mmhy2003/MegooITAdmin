import type { ReactNode } from "react";
import type { SeriesState } from "@/components/servers/performance/use-series";
import { Button } from "@/components/ui/button";
import { Card, CardAction, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { type RangeName, type SampleMessage, type Series, type SeriesAnswer, seriesOf } from "@/lib/metrics";

/** Whether an answer arrived without a single point in any of its series. */
export function hasNoPoints(answer: SeriesAnswer | null): boolean {
  return answer !== null && answer.series.every((s) => s.time.length === 0);
}

/** One chart card of the Performance tab: its title and select, and what its read gave. The children are drawn
 * once an answer with points is there; they dim themselves while a new read is on its way. */
export function MetricCard({
  title,
  state,
  empty,
  children,
  action,
}: {
  title: string;
  state: SeriesState;
  empty: boolean;
  children: ReactNode;
  action?: ReactNode;
}) {
  const { answer, failed, retry } = state;
  let body: ReactNode;
  if (failed && answer === null) {
    body = (
      <div className="grid justify-items-start gap-3">
        <p className="text-sm text-muted-foreground">Could not read this chart.</p>
        <Button variant="outline" size="sm" onClick={retry}>
          Try again
        </Button>
      </div>
    );
  } else if (answer === null) {
    body = <Skeleton className="h-45 w-full" />;
  } else if (empty) {
    body = <p className="text-sm text-muted-foreground">No data in this range</p>;
  } else {
    body = children;
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>
          <h3>{title}</h3>
        </CardTitle>
        {action && <CardAction>{action}</CardAction>}
      </CardHeader>
      <CardContent className="grid gap-4">
        {body}
        {failed && answer !== null && (
          <p className="text-xs text-muted-foreground">
            Could not refresh.{" "}
            <Button variant="link" size="xs" className="h-auto p-0 text-xs" onClick={retry}>
              Try again
            </Button>
          </p>
        )}
      </CardContent>
    </Card>
  );
}

/** What the Performance tab gives each card: `interval` is the server's sample interval in seconds, the step of a
 * live range. */
export type PerformanceCardProps = {
  serverId: string;
  range: RangeName;
  sample: SampleMessage | null;
  refill: number;
  interval: number;
};

/** The milliseconds between two points of an answer: its step, or the sample interval in live. */
export function stepMsOf(answer: SeriesAnswer | null, interval: number): number {
  return (answer?.step_seconds ?? interval) * 1000;
}

/** A series of the answer, or an empty one, so a line without data still has its place. */
export function lineSeries(answer: SeriesAnswer | null, metric: string, instance = ""): Series {
  return seriesOf(answer, metric, instance) ?? { metric, instance, time: [], avg: [], min: [], max: [] };
}
