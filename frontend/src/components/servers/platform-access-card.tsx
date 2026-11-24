"use client";

import { useEffect, useState } from "react";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { ApiError, apiFetch } from "@/lib/api";
import { messageFor } from "@/lib/auth/messages";

/** Quotes a value for sh: inside single quotes, each ' becomes '\''. */
function shellQuote(value: string): string {
  return `'${value.replaceAll("'", `'\\''`)}'`;
}

/** The command that prepares a server for the platform's key; --user only when the account is not megoo. */
export function setupCommand(key: string, username: string): string {
  const command = `sudo sh megoo-setup.sh --from <platform-address> --key ${shellQuote(key)}`;
  return username === "megoo" ? command : `${command} --user ${shellQuote(username)}`;
}

/**
 * Tells how to let the platform sign in to a server: download the setup script, run it with the platform's
 * public key (and the account, when it is not megoo), then pin the host key and test the connection.
 */
export function PlatformAccessCard({ username }: { username: string }) {
  const [key, setKey] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    let active = true;
    apiFetch<{ public_key: string }>("/ssh/public-key").then(
      (body) => {
        if (active) setKey(body.public_key);
      },
      (e: unknown) => {
        if (active) setError(e instanceof ApiError ? e.detail : "error");
      },
    );
    return () => {
      active = false;
    };
  }, []);

  useEffect(() => {
    if (!copied) return;
    const timer = setTimeout(() => setCopied(false), 2000);
    return () => clearTimeout(timer);
  }, [copied]);

  async function copy(text: string) {
    await navigator.clipboard.writeText(text);
    setCopied(true);
  }

  const command = key ? setupCommand(key, username) : null;

  return (
    <Card>
      <CardHeader>
        <CardTitle>
          <h3>Platform access</h3>
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-3 text-sm">
        <p>1. Get the setup script:</p>
        <div className="flex flex-wrap items-center gap-2">
          <Button asChild variant="outline" size="sm">
            <a href="/api/ssh/setup-script" download="megoo-setup.sh">
              Download megoo-setup.sh
            </a>
          </Button>
          <span>or take backend/app/ssh/megoo-setup.sh from the repository.</span>
        </div>
        <p>2. Run it as root on the server, with the platform&apos;s address in place of &lt;platform-address&gt;:</p>
        {error && <Alert variant="destructive">{messageFor(error)}</Alert>}
        {command && (
          <div className="flex items-start gap-3 rounded-lg border p-3">
            <code className="font-mono break-all">{command}</code>
            <Button type="button" variant="outline" size="sm" onClick={() => void copy(command)}>
              {copied ? "Copied" : "Copy"}
            </Button>
          </div>
        )}
        <p>3. Pin the host key and test the connection on this page.</p>
        <p className="text-muted-foreground">
          The script accepts the key only from that address. Limit SSH (port 22) to it in the firewall too: see
          docs/server-setup.md.
        </p>
      </CardContent>
    </Card>
  );
}
