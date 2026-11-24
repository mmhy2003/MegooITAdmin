"use client";

import { useEffect, useState } from "react";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { ApiError, apiFetch } from "@/lib/api";
import { messageFor } from "@/lib/auth/messages";

/** Tells how to let the platform sign in to a server: the account to create and the public key to authorize. */
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

  return (
    <Card>
      <CardHeader>
        <CardTitle>
          <h3>Platform access</h3>
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-3 text-sm">
        <p>1. On the server, create the account {username}: not root, not in the docker group.</p>
        <p>2. Add this public key to its ~/.ssh/authorized_keys:</p>
        {error && <Alert variant="destructive">{messageFor(error)}</Alert>}
        {key && (
          <div className="flex items-start gap-3 rounded-lg border p-3">
            <code className="font-mono break-all">{key}</code>
            <Button type="button" variant="outline" size="sm" onClick={() => void copy(key)}>
              {copied ? "Copied" : "Copy"}
            </Button>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
