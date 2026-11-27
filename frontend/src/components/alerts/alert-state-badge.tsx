import { Badge } from "@/components/ui/badge";
import type { AlertState } from "@/lib/alerts";
import { TONE_CLASSES } from "@/lib/checks";

/** Whether an alert is firing, has resolved or was ended: always the word. */
export function AlertStateBadge({ state }: { state: AlertState }) {
  if (state === "firing") return <Badge variant="destructive">Firing</Badge>;
  if (state === "resolved")
    return (
      <Badge variant="outline" className={TONE_CLASSES.green}>
        Resolved
      </Badge>
    );
  return (
    <Badge variant="outline" className={TONE_CLASSES.muted}>
      Ended
    </Badge>
  );
}
