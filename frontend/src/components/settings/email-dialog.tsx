"use client";

import { useState, type FormEvent } from "react";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
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
import { Switch } from "@/components/ui/switch";
import { type EmailSettings, type Severity, SEVERITY_FILTER_LABEL } from "@/lib/alerts";
import { ApiError, apiFetch } from "@/lib/api";
import { messageFor } from "@/lib/auth/messages";
import { cn } from "@/lib/utils";

type Props = {
  email: EmailSettings | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onSaved: () => void;
};

type Security = EmailSettings["security"];

const SECURITIES: { value: Security; label: string }[] = [
  { value: "starttls", label: "STARTTLS" },
  { value: "tls", label: "TLS" },
  { value: "none", label: "None" },
];
const SEVERITIES = Object.keys(SEVERITY_FILTER_LABEL) as Severity[];
const MAX_EXTRA_ADDRESSES = 20;

/** The addresses typed one per line, without the blank lines. */
function linesOf(text: string): string[] {
  return text
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean);
}

/** Sets up the email that alerts send. */
export function EmailDialog({ email, open, onOpenChange, onSaved }: Props) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-xl">
        {/* Unmounted when closed, so the form always starts from the saved settings. */}
        {email && <EmailForm email={email} onSaved={onSaved} />}
      </DialogContent>
    </Dialog>
  );
}

function EmailForm({ email, onSaved }: { email: EmailSettings; onSaved: () => void }) {
  const [enabled, setEnabled] = useState(email.enabled);
  const [host, setHost] = useState(email.host ?? "");
  const [port, setPort] = useState(email.port);
  const [security, setSecurity] = useState<Security>(email.security);
  const [username, setUsername] = useState(email.username ?? "");
  // The saved password is never shown: the field holds only what is typed.
  const [password, setPassword] = useState("");
  const [removePassword, setRemovePassword] = useState(false);
  const [fromName, setFromName] = useState(email.from_name);
  const [fromAddress, setFromAddress] = useState(email.from_address ?? "");
  const [extra, setExtra] = useState(email.extra_addresses.join("\n"));
  const [minSeverity, setMinSeverity] = useState<Severity>(email.min_severity);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const addresses = linesOf(extra);
  const tooMany = addresses.length > MAX_EXTRA_ADDRESSES;

  async function submit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    const body = {
      enabled,
      host,
      port,
      security,
      username,
      from_name: fromName,
      from_address: fromAddress,
      extra_addresses: addresses,
      min_severity: minSeverity,
      // Without a password the saved one stays, "" removes it.
      ...(removePassword ? { password: "" } : password ? { password } : {}),
    };
    try {
      await apiFetch<EmailSettings>("/notifications/email", { method: "PUT", body });
      onSaved();
    } catch (e) {
      setError(messageFor(e instanceof ApiError ? e.detail : "error"));
    }
    setBusy(false);
  }

  return (
    <>
      <DialogHeader>
        <DialogTitle>Email</DialogTitle>
        <DialogDescription>
          Each alert sends one message when it fires and one when it ends, through this mail server.
        </DialogDescription>
      </DialogHeader>
      <form onSubmit={submit} className="grid gap-4">
        {error && <Alert variant="destructive">{error}</Alert>}
        <div className="flex items-center gap-2">
          <Switch id="email-enabled" checked={enabled} onCheckedChange={setEnabled} />
          <Label htmlFor="email-enabled">Enabled</Label>
        </div>
        <div className="grid gap-4 sm:grid-cols-[1fr_8rem]">
          <div className="space-y-2">
            <Label htmlFor="email-host">Host</Label>
            <Input
              id="email-host"
              required={enabled}
              maxLength={255}
              value={host}
              onChange={(e) => setHost(e.target.value)}
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="email-port">Port</Label>
            <Input
              id="email-port"
              type="number"
              required
              min={1}
              max={65535}
              step={1}
              value={Number.isNaN(port) ? "" : port}
              onChange={(e) => setPort(e.target.valueAsNumber)}
            />
          </div>
        </div>
        <div className="space-y-2">
          <Label id="email-security">Security</Label>
          <RadioGroup
            aria-labelledby="email-security"
            value={security}
            onValueChange={(s) => setSecurity(s as Security)}
            className="flex h-9 items-center gap-4"
          >
            {SECURITIES.map(({ value, label }) => (
              <div key={value} className="flex items-center gap-2">
                <RadioGroupItem id={`email-security-${value}`} value={value} />
                <Label htmlFor={`email-security-${value}`} className="font-normal">
                  {label}
                </Label>
              </div>
            ))}
          </RadioGroup>
        </div>
        <div className="grid gap-4 sm:grid-cols-2">
          <div className="space-y-2">
            <Label htmlFor="email-username">User name</Label>
            <Input
              id="email-username"
              autoComplete="off"
              maxLength={255}
              value={username}
              onChange={(e) => setUsername(e.target.value)}
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="email-password">Password</Label>
            <Input
              id="email-password"
              type="password"
              autoComplete="new-password"
              maxLength={1024}
              placeholder={email.password_set ? "Saved, type to replace" : undefined}
              disabled={removePassword}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
            />
            {email.password_set && (
              <div className="flex items-center gap-2">
                <Checkbox
                  id="email-remove-password"
                  checked={removePassword}
                  onCheckedChange={(checked) => {
                    setRemovePassword(checked === true);
                    setPassword("");
                  }}
                />
                <Label htmlFor="email-remove-password" className="font-normal">
                  Remove the saved password
                </Label>
              </div>
            )}
          </div>
        </div>
        <div className="grid gap-4 sm:grid-cols-2">
          <div className="space-y-2">
            <Label htmlFor="email-from-name">From name</Label>
            <Input
              id="email-from-name"
              required
              maxLength={200}
              value={fromName}
              onChange={(e) => setFromName(e.target.value)}
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="email-from-address">From address</Label>
            <Input
              id="email-from-address"
              type="email"
              required={enabled}
              value={fromAddress}
              onChange={(e) => setFromAddress(e.target.value)}
            />
          </div>
        </div>
        <div className="space-y-2">
          <Label htmlFor="email-extra">Extra addresses</Label>
          <textarea
            id="email-extra"
            rows={4}
            aria-describedby="email-extra-hint"
            aria-invalid={tooMany || undefined}
            className={cn(
              "w-full min-w-0 rounded-md border border-input bg-transparent px-3 py-2 text-base shadow-xs transition-[color,box-shadow] outline-none placeholder:text-muted-foreground md:text-sm dark:bg-input/30",
              "focus-visible:border-ring focus-visible:ring-[3px] focus-visible:ring-ring/50",
              "aria-invalid:border-destructive aria-invalid:ring-destructive/20 dark:aria-invalid:ring-destructive/40",
            )}
            value={extra}
            onChange={(e) => setExtra(e.target.value)}
          />
          <p id="email-extra-hint" className={cn("text-sm", tooMany ? "text-destructive" : "text-muted-foreground")}>
            One per line, {MAX_EXTRA_ADDRESSES} at most. They get every alert the filter lets through.
          </p>
        </div>
        <div className="space-y-2">
          <Label id="email-severity">Sends</Label>
          <RadioGroup
            aria-labelledby="email-severity"
            value={minSeverity}
            onValueChange={(s) => setMinSeverity(s as Severity)}
            className="flex h-9 items-center gap-4"
          >
            {SEVERITIES.map((s) => (
              <div key={s} className="flex items-center gap-2">
                <RadioGroupItem id={`email-severity-${s}`} value={s} />
                <Label htmlFor={`email-severity-${s}`} className="font-normal">
                  {SEVERITY_FILTER_LABEL[s]}
                </Label>
              </div>
            ))}
          </RadioGroup>
        </div>
        <DialogFooter>
          <Button type="submit" disabled={busy || tooMany}>
            Save
          </Button>
        </DialogFooter>
      </form>
    </>
  );
}
