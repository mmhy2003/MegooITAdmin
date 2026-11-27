"use client";

import { Mail, Pencil, Send } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { EmailDialog } from "@/components/settings/email-dialog";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardAction, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { type Delivery, type EmailSettings, SEVERITY_FILTER_LABEL } from "@/lib/alerts";
import { ApiError, apiFetch } from "@/lib/api";
import { deliveryErrorText, messageFor } from "@/lib/auth/messages";
import { agoText } from "@/lib/checks";

type TestResult = { ok: boolean; error: string | null };

function recipientsText(extra: number): string {
  const roles = "The Owner and the Admins of the server's group";
  if (extra === 0) return roles;
  return `${roles}, plus ${extra} more ${extra === 1 ? "address" : "addresses"}`;
}

/** The state of the last message sent to a channel or by email. A failed one is given up after 6 tries. */
function DeliveryText({ delivery }: { delivery: Delivery | null }) {
  if (delivery === null) return <>No message sent yet.</>;
  if (delivery.state === "pending") return <>Waiting to be sent.</>;
  if (delivery.state === "delivered") return <>Delivered {agoText(delivery.at, new Date())}.</>;
  return <span className="text-pink-ink">Failed after 6 tries: {deliveryErrorText(delivery.error)}</span>;
}

/** The Notifications tab of Settings: the email alerts send, and (next) the webhooks and chats. */
export function NotificationsPage() {
  const [email, setEmail] = useState<EmailSettings | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [editing, setEditing] = useState(false);
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState<{ ok: boolean; text: string } | null>(null);

  const reload = useCallback(
    () =>
      apiFetch<EmailSettings>("/notifications/email").then(
        (settings) => {
          setEmail(settings);
          setError(null);
        },
        (e: unknown) => setError(e instanceof ApiError ? e.detail : "error"),
      ),
    [],
  );

  useEffect(() => {
    void reload();
  }, [reload]);

  async function sendTest() {
    setTesting(true);
    setTestResult(null);
    try {
      const result = await apiFetch<TestResult>("/notifications/email/test", { method: "POST" });
      setTestResult(
        result.ok ? { ok: true, text: "Test sent to your address." } : { ok: false, text: deliveryErrorText(result.error) },
      );
    } catch (e) {
      setTestResult({ ok: false, text: messageFor(e instanceof ApiError ? e.detail : "error") });
    }
    setTesting(false);
  }

  function saved() {
    setEditing(false);
    setTestResult(null);
    void reload();
  }

  const setUp = email !== null && email.host !== null;

  return (
    <div className="space-y-6">
      {error && <Alert variant="destructive">{messageFor(error)}</Alert>}
      <Card>
        <CardHeader>
          <CardTitle>
            <h2>Email</h2>
          </CardTitle>
          {email && (
            <CardAction>
              {setUp ? (
                <Button variant="outline" onClick={() => setEditing(true)}>
                  <Pencil aria-hidden />
                  Edit
                </Button>
              ) : (
                <Button onClick={() => setEditing(true)}>
                  <Mail aria-hidden />
                  Set up email
                </Button>
              )}
            </CardAction>
          )}
        </CardHeader>
        <CardContent className="space-y-4">
          {email && !setUp && (
            <p className="text-sm text-muted-foreground">Email is not set up. Alerts are shown in the app only.</p>
          )}
          {email && setUp && (
            <>
              {!email.enabled && <p className="text-sm text-muted-foreground">Email is switched off.</p>}
              <dl className="grid gap-x-6 gap-y-2 text-sm sm:grid-cols-[auto_1fr]">
                <dt className="text-muted-foreground">Server</dt>
                <dd>
                  {email.host}:{email.port}
                </dd>
                <dt className="text-muted-foreground">From</dt>
                <dd>{`${email.from_name} <${email.from_address ?? ""}>`}</dd>
                <dt className="text-muted-foreground">To</dt>
                <dd>{recipientsText(email.extra_addresses.length)}</dd>
                <dt className="text-muted-foreground">Sends</dt>
                <dd>{SEVERITY_FILTER_LABEL[email.min_severity]}</dd>
                <dt className="text-muted-foreground">Last message</dt>
                <dd>
                  <DeliveryText delivery={email.last_delivery} />
                </dd>
              </dl>
              <div className="flex flex-wrap items-center gap-3">
                <Button variant="outline" disabled={testing} onClick={() => void sendTest()}>
                  <Send aria-hidden />
                  Send a test
                </Button>
                <p aria-live="polite" className={testResult?.ok === false ? "text-sm text-pink-ink" : "text-sm"}>
                  {testResult?.text}
                </p>
              </div>
            </>
          )}
        </CardContent>
      </Card>
      <Card>
        <CardHeader>
          <CardTitle>
            <h2>Webhooks and chat</h2>
          </CardTitle>
        </CardHeader>
      </Card>
      <EmailDialog email={email} open={editing} onOpenChange={setEditing} onSaved={saved} />
    </div>
  );
}
