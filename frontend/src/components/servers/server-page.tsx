"use client";

import { Pencil, PlugZap, Trash2 } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";
import { formatTime } from "@/components/profile/profile-page";
import { ConnectionResult } from "@/components/servers/connection-result";
import { Field } from "@/components/servers/field";
import { HostKeyDialog } from "@/components/servers/host-key-dialog";
import { MonitoringBadge } from "@/components/servers/monitoring-badge";
import { MonitoringCard } from "@/components/servers/monitoring-card";
import { PlatformAccessCard } from "@/components/servers/platform-access-card";
import { RemoveServerDialog } from "@/components/servers/remove-server-dialog";
import { ReviewHostKeyDialog } from "@/components/servers/review-host-key-dialog";
import { ServerDialog } from "@/components/servers/server-dialog";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { useRefresh } from "@/hooks/use-refresh";
import type { ServerGroup } from "@/lib/access";
import { ApiError, apiFetch } from "@/lib/api";
import { messageFor } from "@/lib/auth/messages";
import { OS_LABELS, type ConnectionTestResult, type HostKeyState, type Server } from "@/lib/servers";

/** What the Edit dialog offers: the groups the person manages and the tags in use. */
type Choices = { groups: ServerGroup[]; tags: string[] };

/** The badge beside the OS badge for each host key state a Linux server has. */
const STATE_BADGES: Record<Exclude<HostKeyState, "none">, { label: string; variant: "secondary" | "outline" | "destructive" }> =
  {
    pinned: { label: "Host key pinned", variant: "secondary" },
    not_pinned: { label: "Host key not pinned", variant: "outline" },
    changed: { label: "Host key changed", variant: "destructive" },
  };

/** One server's page: its name and badges, and the Overview tab (the other tabs come later). */
export function ServerPage({ serverId }: { serverId: string }) {
  const router = useRouter();
  const [server, setServer] = useState<Server | null>(null);
  const [missing, setMissing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [choices, setChoices] = useState<Choices | null>(null);
  const [editing, setEditing] = useState(false);
  const [removing, setRemoving] = useState(false);
  const [pinning, setPinning] = useState(false);
  const [reviewing, setReviewing] = useState(false);
  const [testing, setTesting] = useState(false);
  const [result, setResult] = useState<ConnectionTestResult | null>(null);
  const [testError, setTestError] = useState<string | null>(null);
  // Each foreground read takes a number; an answer is applied only while its read is still the latest.
  const reads = useRef(0);

  const reload = useCallback(() => {
    const read = ++reads.current;
    return apiFetch<Server>(`/servers/${serverId}`).then(
      (found) => {
        if (read !== reads.current) return;
        setServer(found);
        setMissing(false);
        setError(null);
      },
      (e: unknown) => {
        if (read !== reads.current) return;
        if (e instanceof ApiError && e.status === 404) {
          setServer(null);
          setMissing(true);
        } else {
          setError(e instanceof ApiError ? e.detail : "error");
        }
      },
    );
  }, [serverId]);

  useEffect(() => {
    void reload();
  }, [reload]);

  /** The automatic re-read: it takes no number, so a newer read wins, and a failure other than 404 shows nothing. */
  const refresh = useCallback(() => {
    const read = reads.current;
    apiFetch<Server>(`/servers/${serverId}`, { background: true }).then(
      (found) => {
        if (reads.current === read) setServer(found);
      },
      (e: unknown) => {
        if (reads.current === read && e instanceof ApiError && e.status === 404) {
          setServer(null);
          setMissing(true);
        }
      },
    );
  }, [serverId]);

  useRefresh(refresh, !editing && !removing && !pinning && !reviewing && !testing);

  function edit() {
    Promise.all([apiFetch<ServerGroup[]>("/server-groups"), apiFetch<string[]>("/server-tags")]).then(
      ([groups, tags]) => {
        setChoices({ groups: groups.filter((g) => g.can_manage), tags });
        setEditing(true);
      },
      (e: unknown) => setError(e instanceof ApiError ? e.detail : "error"),
    );
  }

  function saved() {
    setEditing(false);
    void reload();
  }

  async function testConnection() {
    setTesting(true);
    setResult(null);
    setTestError(null);
    try {
      setResult(await apiFetch<ConnectionTestResult>(`/servers/${serverId}/connection-test`, { method: "POST" }));
      void reload();
    } catch (e) {
      setTestError(messageFor(e instanceof ApiError ? e.detail : "error"));
      if (e instanceof ApiError && [403, 404, 409].includes(e.status)) void reload();
    }
    setTesting(false);
  }

  /** A pin or a review changed the server: show it as it is now, without the last test's result. */
  function keyChanged(changed: Server) {
    setPinning(false);
    setReviewing(false);
    reads.current += 1;
    setServer(changed);
    setResult(null);
    setTestError(null);
  }

  if (missing) {
    return (
      <Card>
        <CardContent className="space-y-4">
          <p>This server does not exist, or you cannot see it.</p>
          <Button variant="outline" asChild>
            <Link href="/servers">Back to servers</Link>
          </Button>
        </CardContent>
      </Card>
    );
  }

  return (
    <div className="space-y-6">
      {error && <Alert variant="destructive">{messageFor(error)}</Alert>}
      {server && (
        <>
          <div className="flex flex-wrap items-center justify-between gap-4">
            <div className="flex flex-wrap items-center gap-2">
              <h2 className="text-xl font-semibold tracking-tight">{server.name}</h2>
              <MonitoringBadge monitoring={server.monitoring} />
              <Badge variant="secondary">{OS_LABELS[server.os]}</Badge>
              {server.host_key_state !== "none" && (
                <Badge variant={STATE_BADGES[server.host_key_state].variant}>
                  {STATE_BADGES[server.host_key_state].label}
                </Badge>
              )}
              <Badge variant="outline">{server.group_name}</Badge>
            </div>
            <div className="flex flex-wrap gap-2">
              {server.can_connect && server.host_key_state !== "none" && (
                <Button
                  variant="outline"
                  disabled={testing || server.host_key_state !== "pinned"}
                  onClick={() => void testConnection()}
                >
                  <PlugZap aria-hidden />
                  {testing ? "Testing…" : "Test connection"}
                </Button>
              )}
              {server.can_manage && (
                <>
                  <Button variant="outline" onClick={edit}>
                    <Pencil aria-hidden />
                    Edit
                  </Button>
                  <Button variant="outline" onClick={() => setRemoving(true)}>
                    <Trash2 aria-hidden />
                    Remove
                  </Button>
                </>
              )}
            </div>
          </div>
          {result && <ConnectionResult result={result} />}
          {testError && <Alert variant="destructive">{testError}</Alert>}
          {server.host_key_state === "not_pinned" && (
            <Alert>
              <AlertDescription className="flex flex-wrap items-center justify-between gap-3 text-foreground">
                <p>The host key of {server.name} is not pinned yet. Nothing connects to it until it is.</p>
                {server.can_manage ? (
                  <Button size="sm" onClick={() => setPinning(true)}>
                    Pin host key
                  </Button>
                ) : (
                  <p>Ask an Admin of {server.group_name} to pin it.</p>
                )}
              </AlertDescription>
            </Alert>
          )}
          {server.host_key_state === "changed" && (
            <Alert variant="destructive">
              <AlertTitle>Host key changed: connections to {server.name} are blocked</AlertTitle>
              <AlertDescription>
                {server.host_key_changed_at && (
                  <p>
                    On {formatTime(server.host_key_changed_at)} the server presented another host key than the pinned
                    one. The server may have been reinstalled, or someone may be in the way.
                  </p>
                )}
                {server.host_key_offered === null && <p>The new key could not be read.</p>}
                {server.can_manage ? (
                  <Button size="sm" variant="destructive" onClick={() => setReviewing(true)}>
                    Review host key
                  </Button>
                ) : (
                  <p>An Admin of {server.group_name} must review it.</p>
                )}
              </AlertDescription>
            </Alert>
          )}
          <div role="tablist" aria-label="Server" className="flex gap-2 border-b">
            <button
              type="button"
              role="tab"
              aria-selected="true"
              className="-mb-px border-b-2 border-primary px-3 py-2 text-sm font-semibold"
            >
              Overview
            </button>
          </div>
          <MonitoringCard server={server} />
          <div className="grid gap-6 md:grid-cols-2">
            <Card>
              <CardHeader>
                <CardTitle>
                  <h3>Connection</h3>
                </CardTitle>
              </CardHeader>
              <CardContent>
                <dl className="space-y-3">
                  <Field label="Address">
                    <span className="font-mono">{server.address}</span>
                  </Field>
                  <Field label="Port">
                    <span className="font-mono">{server.port}</span>
                  </Field>
                  <Field label="Login account">
                    <span className="font-mono">{server.connection_settings.username}</span>
                  </Field>
                  {server.os !== "windows" && (
                    <Field label="Host key">
                      {server.host_key_fingerprint === null ? (
                        <span className="text-muted-foreground">Not pinned yet</span>
                      ) : (
                        <div className="space-y-1">
                          <span className="block font-mono break-all">{server.host_key_fingerprint}</span>
                          <span className="block text-sm text-muted-foreground">
                            {server.host_key_type}
                            {server.host_key_pinned_at && ` · Pinned ${formatTime(server.host_key_pinned_at)}`}
                          </span>
                        </div>
                      )}
                    </Field>
                  )}
                </dl>
              </CardContent>
            </Card>
            <Card>
              <CardHeader>
                <CardTitle>
                  <h3>Details</h3>
                </CardTitle>
              </CardHeader>
              <CardContent>
                <dl className="space-y-3">
                  <Field label="Server group">{server.group_name}</Field>
                  <Field label="Operating system">{OS_LABELS[server.os]}</Field>
                  <Field label="Role">{server.role ?? <span className="text-muted-foreground">None</span>}</Field>
                  <Field label="Tags">
                    {server.tags.length > 0 ? (
                      <div className="flex flex-wrap gap-1">
                        {server.tags.map((tag) => (
                          <Badge key={tag} variant="secondary">
                            {tag}
                          </Badge>
                        ))}
                      </div>
                    ) : (
                      <span className="text-muted-foreground">None</span>
                    )}
                  </Field>
                  <Field label="Registered">{formatTime(server.created_at)}</Field>
                  <Field label="Last changed">{formatTime(server.updated_at)}</Field>
                </dl>
              </CardContent>
            </Card>
          </div>
          {server.can_manage && server.os === "linux" && (
            <PlatformAccessCard username={server.connection_settings.username} />
          )}
          <HostKeyDialog
            server={server}
            open={pinning}
            onOpenChange={setPinning}
            onPinned={keyChanged}
            onStale={() => void reload()}
          />
          <ReviewHostKeyDialog
            server={server}
            open={reviewing}
            onOpenChange={setReviewing}
            onDone={keyChanged}
            onStale={() => void reload()}
          />
        </>
      )}
      <ServerDialog
        server={server}
        groups={choices?.groups ?? []}
        defaultGroupId={null}
        tags={choices?.tags ?? []}
        open={editing && server !== null}
        onOpenChange={setEditing}
        onSaved={saved}
        onStale={() => void reload()}
      />
      <RemoveServerDialog
        server={server}
        open={removing}
        onOpenChange={setRemoving}
        onRemoved={() => router.push("/servers")}
      />
    </div>
  );
}
