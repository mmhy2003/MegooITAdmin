import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { reasonText } from "@/lib/auth/messages";
import { CHECK_LABELS, CHECK_STATUS_LABELS, type ConnectionTestResult } from "@/lib/servers";

/** The result of a connection test: its four checks and, when it failed, what to do. */
export function ConnectionResult({ result }: { result: ConnectionTestResult }) {
  const reason = !result.ok && result.reason ? reasonText(result.reason) : null;
  return (
    <Alert role="status" variant={result.ok ? "default" : "destructive"}>
      <AlertTitle>{reason ? reason.title : "Connection works"}</AlertTitle>
      <AlertDescription>
        <ul aria-label="Checks" className="grid gap-1">
          {result.checks.map((check) => (
            <li key={check.name} className="flex flex-wrap gap-x-2">
              <span>{CHECK_LABELS[check.name]}</span>
              <span className="font-medium">{CHECK_STATUS_LABELS[check.status]}</span>
            </li>
          ))}
        </ul>
        {reason && <p>{reason.advice}</p>}
      </AlertDescription>
    </Alert>
  );
}
