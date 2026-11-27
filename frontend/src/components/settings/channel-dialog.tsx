"use client";

import { useState, type FormEvent } from "react";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { RadioGroup, RadioGroupItem } from "@/components/ui/radio-group";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { type Channel, type ChannelKind, type Severity, SEVERITY_FILTER_LABEL } from "@/lib/alerts";
import { ApiError, apiFetch } from "@/lib/api";
import { messageFor } from "@/lib/auth/messages";

type Props = {
  channel?: Channel | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onSaved: () => void;
};

export const CHANNEL_KIND_LABEL: Record<ChannelKind, string> = {
  webhook_json: "Generic JSON",
  webhook_slack: "Slack-compatible",
  telegram: "Telegram",
};

type ChannelBody = {
  name?: string;
  kind?: ChannelKind;
  min_severity?: Severity;
  enabled?: boolean;
  url?: string;
  bot_token?: string;
  chat_id?: string;
};

const KINDS = Object.keys(CHANNEL_KIND_LABEL) as ChannelKind[];
const SEVERITIES = Object.keys(SEVERITY_FILTER_LABEL) as Severity[];
const SAVED = "Saved, type to replace";

/** Both webhook formats keep an address, a Telegram chat a bot token and a chat ID. */
function isWebhook(kind: ChannelKind): boolean {
  return kind !== "telegram";
}

/** Adds a webhook or a Telegram chat, or edits `channel`. */
export function ChannelDialog({ channel, open, onOpenChange, onSaved }: Props) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-xl">
        {/* Keyed by the channel, and unmounted when closed, so the form always starts from the saved channel. */}
        <ChannelForm key={channel?.id ?? "new"} channel={channel ?? null} onSaved={onSaved} />
      </DialogContent>
    </Dialog>
  );
}

function ChannelForm({ channel, onSaved }: { channel: Channel | null; onSaved: () => void }) {
  const [name, setName] = useState(channel?.name ?? "");
  const [kind, setKind] = useState<ChannelKind>(channel?.kind ?? "webhook_json");
  const [minSeverity, setMinSeverity] = useState<Severity>(channel?.min_severity ?? "warning");
  const [enabled, setEnabled] = useState(channel?.enabled ?? true);
  // The saved secret is never shown: the fields hold only what is typed.
  const [url, setUrl] = useState("");
  const [botToken, setBotToken] = useState("");
  const [chatId, setChatId] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // The saved secret is kept while the kind keeps the same parts; another kind needs its own.
  const saved = channel !== null && isWebhook(channel.kind) === isWebhook(kind);
  const secret = isWebhook(kind) ? { url } : { bot_token: botToken, chat_id: chatId };
  const typed = Object.fromEntries(Object.entries(secret).filter(([, value]) => value !== ""));
  const fields = { name: name.trim(), kind, min_severity: minSeverity, enabled };
  const body: ChannelBody = channel
    ? {
        ...Object.fromEntries(Object.entries(fields).filter(([key, value]) => channel[key as keyof Channel] !== value)),
        ...typed,
      }
    : { ...fields, ...typed };
  const unchanged = channel !== null && Object.keys(body).length === 0;

  async function submit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      if (channel) {
        await apiFetch<Channel>(`/notification-channels/${channel.id}`, { method: "PATCH", body });
      } else {
        await apiFetch<Channel>("/notification-channels", { method: "POST", body });
      }
      onSaved();
    } catch (e) {
      setError(messageFor(e instanceof ApiError ? e.detail : "error"));
    }
    setBusy(false);
  }

  const savedHint = saved && (
    <p id="channel-saved" className="text-sm text-muted-foreground">
      Saved: {channel.hint}.
    </p>
  );

  return (
    <>
      <DialogHeader>
        <DialogTitle>{channel ? `Edit ${channel.name}` : "Add a channel"}</DialogTitle>
        <DialogDescription>Each alert sends one message here when it fires and one when it ends.</DialogDescription>
      </DialogHeader>
      <form onSubmit={submit} className="grid gap-4">
        {error && <Alert variant="destructive">{error}</Alert>}
        <div className="space-y-2">
          <Label htmlFor="channel-name">Name</Label>
          <Input id="channel-name" required maxLength={80} value={name} onChange={(e) => setName(e.target.value)} />
        </div>
        <div className="space-y-2">
          <Label htmlFor="channel-kind">Kind</Label>
          <Select value={kind} onValueChange={(k) => setKind(k as ChannelKind)}>
            <SelectTrigger id="channel-kind" aria-label="Kind" className="w-full">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {KINDS.map((k) => (
                <SelectItem key={k} value={k}>
                  {CHANNEL_KIND_LABEL[k]}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        {isWebhook(kind) ? (
          <div className="space-y-2">
            <Label htmlFor="channel-url">URL</Label>
            <Input
              id="channel-url"
              type="url"
              autoComplete="off"
              required={!saved}
              maxLength={2048}
              placeholder={saved ? SAVED : undefined}
              aria-describedby={saved ? "channel-saved channel-url-hint" : "channel-url-hint"}
              value={url}
              onChange={(e) => setUrl(e.target.value)}
            />
            {savedHint}
            <p id="channel-url-hint" className="text-sm text-muted-foreground">
              The Slack format also works with Mattermost, Rocket.Chat, Google Chat and Discord (add /slack to its
              address).
            </p>
          </div>
        ) : (
          <div className="space-y-2">
            <div className="grid gap-4 sm:grid-cols-2">
              <div className="space-y-2">
                <Label htmlFor="channel-bot-token">Bot token</Label>
                <Input
                  id="channel-bot-token"
                  type="password"
                  autoComplete="new-password"
                  required={!saved}
                  maxLength={200}
                  placeholder={saved ? SAVED : undefined}
                  aria-describedby={saved ? "channel-saved" : undefined}
                  value={botToken}
                  onChange={(e) => setBotToken(e.target.value)}
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="channel-chat-id">Chat ID</Label>
                <Input
                  id="channel-chat-id"
                  autoComplete="off"
                  required={!saved}
                  maxLength={64}
                  placeholder={saved ? SAVED : undefined}
                  aria-describedby={saved ? "channel-saved" : undefined}
                  value={chatId}
                  onChange={(e) => setChatId(e.target.value)}
                />
              </div>
            </div>
            {savedHint}
          </div>
        )}
        <div className="space-y-2">
          <Label id="channel-severity">Sends</Label>
          <RadioGroup
            aria-labelledby="channel-severity"
            value={minSeverity}
            onValueChange={(s) => setMinSeverity(s as Severity)}
            className="flex h-9 items-center gap-4"
          >
            {SEVERITIES.map((s) => (
              <div key={s} className="flex items-center gap-2">
                <RadioGroupItem id={`channel-severity-${s}`} value={s} />
                <Label htmlFor={`channel-severity-${s}`} className="font-normal">
                  {SEVERITY_FILTER_LABEL[s]}
                </Label>
              </div>
            ))}
          </RadioGroup>
        </div>
        <div className="flex items-center gap-2">
          <Switch id="channel-enabled" checked={enabled} onCheckedChange={setEnabled} />
          <Label htmlFor="channel-enabled">Enabled</Label>
        </div>
        <DialogFooter>
          <Button type="submit" disabled={busy || unchanged}>
            Save
          </Button>
        </DialogFooter>
      </form>
    </>
  );
}
