"use client";

import { Pencil, Trash2 } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState, type ReactNode } from "react";
import { formatTime } from "@/components/profile/profile-page";
import { RemoveServerDialog } from "@/components/servers/remove-server-dialog";
import { ServerDialog } from "@/components/servers/server-dialog";
import { Alert } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import type { ServerGroup } from "@/lib/access";
import { ApiError, apiFetch } from "@/lib/api";
import { messageFor } from "@/lib/auth/messages";
import { OS_LABELS, type Server } from "@/lib/servers";

/** What the Edit dialog offers: the groups the person manages and the tags in use. */
type Choices = { groups: ServerGroup[]; tags: string[] };

/** One server's page: its name and badges, and the Overview tab (the other tabs come later). */
export function ServerPage({ serverId }: { serverId: string }) {
  const router = useRouter();
  const [server, setServer] = useState<Server | null>(null);
  const [missing, setMissing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [choices, setChoices] = useState<Choices | null>(null);
  const [editing, setEditing] = useState(false);
  const [removing, setRemoving] = useState(false);

  const reload = useCallback(
    () =>
      apiFetch<Server>(`/servers/${serverId}`).then(
        (found) => {
          setServer(found);
          setMissing(false);
          setError(null);
        },
        (e: unknown) => {
          if (e instanceof ApiError && e.status === 404) {
            setServer(null);
            setMissing(true);
          } else {
            setError(e instanceof ApiError ? e.detail : "error");
          }
        },
      ),
    [serverId],
  );

  useEffect(() => {
    void reload();
  }, [reload]);

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
              <Badge variant="secondary">{OS_LABELS[server.os]}</Badge>
              <Badge variant="outline">{server.group_name}</Badge>
            </div>
            {server.can_manage && (
              <div className="flex flex-wrap gap-2">
                <Button variant="outline" onClick={edit}>
                  <Pencil aria-hidden />
                  Edit
                </Button>
                <Button variant="outline" onClick={() => setRemoving(true)}>
                  <Trash2 aria-hidden />
                  Remove
                </Button>
              </div>
            )}
          </div>
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
                  <Field label="Host key">
                    {server.host_key ? (
                      <span className="font-mono break-all">{server.host_key}</span>
                    ) : (
                      <span className="text-muted-foreground">Not pinned yet</span>
                    )}
                  </Field>
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

function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="space-y-1">
      <dt className="text-sm text-muted-foreground">{label}</dt>
      <dd>{children}</dd>
    </div>
  );
}
