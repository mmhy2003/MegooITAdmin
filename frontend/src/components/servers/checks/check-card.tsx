import type { ReactNode } from "react";
import { Badge } from "@/components/ui/badge";
import { Card, CardAction, CardContent, CardFooter, CardHeader, CardTitle } from "@/components/ui/card";
import {
  agoText,
  type CheckState,
  everyText,
  isOld,
  NOT_AVAILABLE,
  type ServerCheck,
  STATE_TEXTS,
  TONE_CLASSES,
} from "@/lib/checks";
import { cn } from "@/lib/utils";

const STATE_CLASSES: Record<Exclude<CheckState, "ok">, string> = {
  not_checked: cn(TONE_CLASSES.muted, "border-dashed"),
  not_available: TONE_CLASSES.muted,
  denied: TONE_CLASSES.amber,
  timeout: TONE_CLASSES.amber,
  failed: TONE_CLASSES.amber,
};

/** The frame of one check: its title and state, its result, and when it last ran. */
export function CheckCard({
  title,
  check,
  now,
  okBadge,
  footnote,
  children,
}: {
  title: string;
  check: ServerCheck;
  now: Date;
  okBadge?: ReactNode;
  footnote?: string;
  children?: ReactNode;
}) {
  const { status } = check;
  const hasData = check.data !== null;
  return (
    <Card>
      <CardHeader>
        <CardTitle>
          <h3>{title}</h3>
        </CardTitle>
        <CardAction>
          {status === "ok" ? (
            okBadge
          ) : (
            <Badge variant="outline" className={STATE_CLASSES[status]}>
              {STATE_TEXTS[status].badge}
            </Badge>
          )}
        </CardAction>
      </CardHeader>
      <CardContent className="space-y-3">
        {hasData && children}
        {status !== "ok" && (
          <div className="space-y-1">
            <p>{status === "not_available" ? NOT_AVAILABLE[check.kind] : STATE_TEXTS[status].text}</p>
            {hasData && check.data_at !== null && (
              <p className="text-sm text-muted-foreground">Showing the result from {agoText(check.data_at, now)}.</p>
            )}
          </div>
        )}
      </CardContent>
      <CardFooter data-testid="check-footer" className="flex-col items-start gap-1 text-sm text-muted-foreground">
        {check.checked_at !== null && (
          <p className={cn(isOld(check, now) && "text-amber-ink")}>
            {isOld(check, now) ? "Last checked" : "Checked"} {agoText(check.checked_at, now)} ·{" "}
            {everyText(check.every_seconds)}
          </p>
        )}
        {footnote && <p>{footnote}</p>}
      </CardFooter>
    </Card>
  );
}
