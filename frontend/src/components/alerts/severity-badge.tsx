import { Badge } from "@/components/ui/badge";
import { SEVERITY_LABEL, type Severity } from "@/lib/alerts";
import { TONE_CLASSES } from "@/lib/checks";

/** How bad an alert is: always the word, Warning in amber and Critical in pink. */
export function SeverityBadge({ severity }: { severity: Severity }) {
  if (severity === "critical") return <Badge variant="destructive">{SEVERITY_LABEL.critical}</Badge>;
  return (
    <Badge variant="outline" className={TONE_CLASSES.amber}>
      {SEVERITY_LABEL.warning}
    </Badge>
  );
}
