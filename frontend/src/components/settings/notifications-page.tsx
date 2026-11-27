"use client";

import { Mail, Pencil, Plus, Send, Trash2 } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { CHANNEL_KIND_LABEL, ChannelDialog } from "@/components/settings/channel-dialog";
import { DeleteChannelDialog } from "@/components/settings/delete-channel-dialog";
import { EmailDialog } from "@/components/settings/email-dialog";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardAction, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { type Channel, type Delivery, type EmailSettings, SEVERITY_FILTER_LABEL } from "@/lib/alerts";
import { ApiError, apiFetch } from "@/lib/api";
import { deliveryErrorText, messageFor } from "@/lib/auth/messages";
import { agoText } from "@/lib/checks";

type TestResult = { ok: boolean; error: string | null };

function recipientsText(extra: number): string {
  const roles = "The Owner and the Admins of the server's group";
  if (extra === 0) return roles;
  return `${roles}, plus ${extra} more ${extra === 1 ? "address" : "addresses"}`;
}

/** The state of the last message sent to a channel or by email. A pending one with an error is retried; a failed one
 * is given up after 6 tries. */
function DeliveryText({ delivery }: { delivery: Delivery | null }) {
  if (delivery === null) return <>No message sent yet.</>;
  if (delivery.state === "pending" && delivery.error !== null) return <>Retrying: {deliveryErrorText(delivery.error)}</>;
  if (delivery.state === "pending") return <>Waiting to be sent.</>;
  if (delivery.state === "delivered") return <>Delivered {agoText(delivery.at, new Date())}.</>;
  return <span className="text-pink-ink">Failed after 6 tries: {deliveryErrorText(delivery.error)}</span>;
}

/** The test result shown next to the channel or the email that was tested. */
function testText(result: TestResult, delivered: string): { ok: boolean; text: string } {
  return result.ok ? { ok: true, text: delivered } : { ok: false, text: deliveryErrorText(result.error) };
}

/** The Notifications tab of Settings: the email alerts send, and the webhooks and Telegram chats. */
export function NotificationsPage() {
  const [email, setEmail] = useState<EmailSettings | null>(null);
  const [error, setError] = useState<string | null>(null);
  // Kept apart, so one load that succeeds does not hide the other's failure.
  const [channelError, setChannelError] = useState<string | null>(null);
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
      setTestResult(testText(result, "Test sent to your address."));
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
  const shownError = error ?? channelError;

  return (
    <div className="space-y-6">
      {shownError && <Alert variant="destructive">{messageFor(shownError)}</Alert>}
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
      <ChannelsCard onError={setChannelError} />
      <EmailDialog email={email} open={editing} onOpenChange={setEditing} onSaved={saved} />
    </div>
  );
}

/** The webhooks and Telegram chats: each one's kind, filter, switch and last message, with a test, Edit and Delete.
 * A failed load or switch goes to the page's alert, with the email's. */
function ChannelsCard({ onError }: { onError: (detail: string | null) => void }) {
  const [channels, setChannels] = useState<Channel[] | null>(null);
  // `undefined` is closed, `null` is a new channel.
  const [editing, setEditing] = useState<Channel | null | undefined>(undefined);
  const [deleting, setDeleting] = useState<Channel | null>(null);
  // The channels whose switch or test is being sent: held so a second click cannot overtake the first.
  const [busy, setBusy] = useState<ReadonlySet<string>>(new Set());
  const [tests, setTests] = useState<Record<string, { ok: boolean; text: string }>>({});

  const reload = useCallback(
    () =>
      apiFetch<Channel[]>("/notification-channels").then(
        (list) => {
          setChannels(list);
          onError(null);
        },
        (e: unknown) => onError(e instanceof ApiError ? e.detail : "error"),
      ),
    [onError],
  );

  useEffect(() => {
    void reload();
  }, [reload]);

  async function holding(channel: Channel, action: () => Promise<void>) {
    setBusy((ids) => new Set(ids).add(channel.id));
    await action();
    setBusy((ids) => {
      const rest = new Set(ids);
      rest.delete(channel.id);
      return rest;
    });
  }

  function toggle(channel: Channel, enabled: boolean) {
    return holding(channel, async () => {
      try {
        await apiFetch<Channel>(`/notification-channels/${channel.id}`, { method: "PATCH", body: { enabled } });
        await reload();
      } catch (e) {
        onError(e instanceof ApiError ? e.detail : "error");
      }
    });
  }

  function sendTest(channel: Channel) {
    return holding(channel, async () => {
      setTests((t) => {
        const rest = { ...t };
        delete rest[channel.id];
        return rest;
      });
      let shown: { ok: boolean; text: string };
      try {
        const result = await apiFetch<TestResult>(`/notification-channels/${channel.id}/test`, { method: "POST" });
        shown = testText(result, "Test delivered.");
      } catch (e) {
        shown = { ok: false, text: messageFor(e instanceof ApiError ? e.detail : "error") };
      }
      setTests((t) => ({ ...t, [channel.id]: shown }));
    });
  }

  function saved() {
    setEditing(undefined);
    void reload();
  }

  function deleted() {
    setDeleting(null);
    void reload();
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>
          <h2>Webhooks and chat</h2>
        </CardTitle>
        <CardAction>
          <Button onClick={() => setEditing(null)}>
            <Plus aria-hidden />
            Add a channel
          </Button>
        </CardAction>
      </CardHeader>
      <CardContent className="space-y-4">
        {channels?.length === 0 && <p className="text-sm text-muted-foreground">No webhooks or chats yet.</p>}
        {channels && channels.length > 0 && (
          <ul className="divide-y">
            {channels.map((channel) => (
              <li key={channel.id} className="space-y-3 py-4 first:pt-0 last:pb-0">
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div className="space-y-1 text-sm">
                    <div className="font-medium">{channel.name}</div>
                    <div className="text-muted-foreground">
                      {`${CHANNEL_KIND_LABEL[channel.kind]} · ${channel.hint}`}
                    </div>
                    <div>{SEVERITY_FILTER_LABEL[channel.min_severity]}</div>
                    <div>
                      <DeliveryText delivery={channel.last_delivery} />
                    </div>
                  </div>
                  <div className="flex items-center gap-2">
                    <Switch
                      id={`channel-enabled-${channel.id}`}
                      checked={channel.enabled}
                      disabled={busy.has(channel.id)}
                      onCheckedChange={(enabled) => void toggle(channel, enabled)}
                    />
                    <Label htmlFor={`channel-enabled-${channel.id}`}>Enabled</Label>
                  </div>
                </div>
                <div className="flex flex-wrap items-center gap-3">
                  <Button variant="outline" disabled={busy.has(channel.id)} onClick={() => void sendTest(channel)}>
                    <Send aria-hidden />
                    Send a test
                  </Button>
                  <Button
                    variant="ghost"
                    size="icon"
                    aria-label={`Edit ${channel.name}`}
                    onClick={() => setEditing(channel)}
                  >
                    <Pencil aria-hidden />
                  </Button>
                  <Button
                    variant="ghost"
                    size="icon"
                    aria-label={`Delete ${channel.name}`}
                    onClick={() => setDeleting(channel)}
                  >
                    <Trash2 aria-hidden />
                  </Button>
                  <p
                    aria-live="polite"
                    className={tests[channel.id]?.ok === false ? "text-sm text-pink-ink" : "text-sm"}
                  >
                    {tests[channel.id]?.text}
                  </p>
                </div>
              </li>
            ))}
          </ul>
        )}
      </CardContent>
      <ChannelDialog
        channel={editing}
        open={editing !== undefined}
        onOpenChange={(open) => !open && setEditing(undefined)}
        onSaved={saved}
      />
      <DeleteChannelDialog
        channel={deleting}
        open={deleting !== null}
        onOpenChange={(open) => !open && setDeleting(null)}
        onDeleted={deleted}
      />
    </Card>
  );
}
