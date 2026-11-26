import { formatTime } from "@/components/profile/profile-page";
import { CheckCard } from "@/components/servers/checks/check-card";
import { Badge } from "@/components/ui/badge";
import { certificateTone, type ServerCheck, TONE_CLASSES } from "@/lib/checks";

const FOOTNOTE =
  "Checks what the server serves on ports 443, 465, 636, 853, 993, 995, 5671, 6443, 8443, 8883 and 9443, for its own host name. Only the default site of each port is seen.";

/** The certificates the server serves on its usual TLS ports, and when they expire. */
export function CertificatesCard({ check, now }: { check: ServerCheck<"certificates">; now: Date }) {
  const certificates = check.data?.certificates ?? [];
  const nearest = certificates.reduce<string | null>(
    (soonest, item) => (soonest === null || item.not_after < soonest ? item.not_after : soonest),
    null,
  );
  const nearestTone = nearest === null ? null : certificateTone(nearest, now);
  const okBadge = (
    <Badge variant="outline" className={TONE_CLASSES[nearestTone?.tone ?? "muted"]}>
      {nearestTone?.label ?? "None"}
    </Badge>
  );
  return (
    <CheckCard title="Certificates" check={check} now={now} okBadge={okBadge} footnote={FOOTNOTE}>
      {certificates.length > 0 ? (
        <ul className="space-y-3">
          {certificates.map((item) => {
            const { tone, label } = certificateTone(item.not_after, now);
            return (
              <li key={item.port} className="flex items-start justify-between gap-3 text-sm">
                <div className="min-w-0 space-y-0.5">
                  <p className="font-medium">Port {item.port}</p>
                  <p className="break-all">{item.subject}</p>
                  <p className="break-all text-muted-foreground">{item.issuer}</p>
                  <p>Expires {formatTime(item.not_after)}</p>
                </div>
                <Badge variant="outline" className={TONE_CLASSES[tone]}>
                  {label}
                </Badge>
              </li>
            );
          })}
        </ul>
      ) : (
        <p>No certificate is served on the usual TLS ports.</p>
      )}
    </CheckCard>
  );
}
