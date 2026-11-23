"use client";

import { MoreHorizontal, UserPlus } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { formatTime } from "@/components/profile/profile-page";
import { AccessDialog } from "@/components/settings/access-dialog";
import { DisableDialog } from "@/components/settings/disable-dialog";
import { InviteDialog } from "@/components/settings/invite-dialog";
import { InviteLinkDialog } from "@/components/settings/invite-link-dialog";
import { Alert } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardAction, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { badgesOf, type InviteLink, type ServerGroup, type UserRow } from "@/lib/access";
import { ApiError, apiFetch } from "@/lib/api";
import { messageFor } from "@/lib/auth/messages";

/** The menu items of a person's row, by the account's status. */
const ACTIONS: Record<UserRow["status"], string[]> = {
  active: ["Change access", "Reset two-step verification", "Disable"],
  invited: ["Change access", "New invite link", "Disable"],
  disabled: ["Change access", "Enable"],
};

function statusOf(row: UserRow): string {
  if (row.status === "invited") {
    return row.invite_expires_at ? `Invited · link expires ${formatTime(row.invite_expires_at)}` : "Invited";
  }
  return row.status === "active" ? "Active" : "Disabled";
}

/** The Users tab of Settings: every account, its access and status, and the Owner's invite. */
export function UsersPage({ currentUserId }: { currentUserId: string }) {
  const [rows, setRows] = useState<UserRow[] | null>(null);
  const [groups, setGroups] = useState<ServerGroup[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [inviting, setInviting] = useState(false);
  const [link, setLink] = useState<{ link: InviteLink; name: string } | null>(null);
  const [changing, setChanging] = useState<UserRow | null>(null);
  const [disabling, setDisabling] = useState<UserRow | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const reload = useCallback(
    () =>
      Promise.all([apiFetch<UserRow[]>("/users"), apiFetch<ServerGroup[]>("/server-groups")]).then(
        ([users, serverGroups]) => {
          setRows(users);
          setGroups(serverGroups);
          setError(null);
        },
        (e: unknown) => setError(e instanceof ApiError ? e.detail : "error"),
      ),
    [],
  );

  useEffect(() => {
    void reload();
  }, [reload]);

  function invited(created: InviteLink, name: string) {
    setInviting(false);
    setLink({ link: created, name });
    void reload();
  }

  function accessSaved() {
    setNotice(`Access of ${changing?.name ?? ""} saved.`);
    setChanging(null);
    void reload();
  }

  function disabled() {
    setDisabling(null);
    void reload();
  }

  /** Runs a menu action that posts at once; a success shows `done` and reloads the list. */
  async function post(row: UserRow, route: string, done: string) {
    setNotice(null);
    try {
      await apiFetch<void>(`/users/${row.id}/${route}`, { method: "POST" });
      setError(null);
      setNotice(done);
    } catch (e) {
      setError(e instanceof ApiError ? e.detail : "error");
      return;
    }
    void reload();
  }

  async function renewInvite(row: UserRow) {
    setNotice(null);
    try {
      const renewed = await apiFetch<InviteLink>(`/users/${row.id}/invite`, { method: "POST" });
      setError(null);
      setLink({ link: renewed, name: row.name });
    } catch (e) {
      setError(e instanceof ApiError ? e.detail : "error");
      return;
    }
    void reload();
  }

  function handlerOf(action: string, row: UserRow): () => void {
    switch (action) {
      case "Change access":
        return () => setChanging(row);
      case "Disable":
        return () => setDisabling(row);
      case "Enable":
        return () => void post(row, "enable", `${row.name} can sign in again.`);
      case "Reset two-step verification":
        return () =>
          void post(
            row,
            "mfa-reset",
            `Two-step verification of ${row.name} is reset. They set up a new authenticator at their next sign-in.`,
          );
      default: // "New invite link"
        return () => void renewInvite(row);
    }
  }

  function reloadGroups() {
    apiFetch<ServerGroup[]>("/server-groups").then(setGroups, () => undefined);
  }

  return (
    <div className="space-y-6">
      {error && <Alert variant="destructive">{messageFor(error)}</Alert>}
      {notice && <Alert>{notice}</Alert>}
      <Card>
        <CardHeader>
          <CardTitle>
            <h2>People</h2>
          </CardTitle>
          <CardAction>
            <Button onClick={() => setInviting(true)}>
              <UserPlus aria-hidden />
              Invite person
            </Button>
          </CardAction>
        </CardHeader>
        <CardContent>
          {rows && (
            <div className="overflow-x-auto">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Name</TableHead>
                    <TableHead>Access</TableHead>
                    <TableHead>Status</TableHead>
                    <TableHead>Two-step</TableHead>
                    <TableHead>
                      <span className="sr-only">Actions</span>
                    </TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {rows.map((row) => (
                    <TableRow key={row.id}>
                      <TableCell>
                        <div className="flex items-center gap-2">
                          <span className="font-medium">{row.name}</span>
                          {row.id === currentUserId && <Badge variant="outline">You</Badge>}
                        </div>
                        <div className="text-sm text-muted-foreground">{row.email}</div>
                      </TableCell>
                      <TableCell>
                        <div className="flex flex-wrap gap-1">
                          {badgesOf(row).map((badge) => (
                            <Badge key={badge} variant="secondary">
                              {badge}
                            </Badge>
                          ))}
                        </div>
                      </TableCell>
                      <TableCell>{statusOf(row)}</TableCell>
                      <TableCell>{row.mfa_enrolled ? "On" : "Not set up"}</TableCell>
                      <TableCell className="text-right">
                        {row.id !== currentUserId && (
                          <DropdownMenu>
                            <DropdownMenuTrigger asChild>
                              <Button variant="ghost" size="icon" aria-label={`Actions for ${row.name}`}>
                                <MoreHorizontal aria-hidden />
                              </Button>
                            </DropdownMenuTrigger>
                            <DropdownMenuContent align="end">
                              {ACTIONS[row.status].map((action) => (
                                <DropdownMenuItem key={action} onSelect={handlerOf(action, row)}>
                                  {action}
                                </DropdownMenuItem>
                              ))}
                            </DropdownMenuContent>
                          </DropdownMenu>
                        )}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          )}
        </CardContent>
      </Card>
      <InviteDialog
        groups={groups}
        open={inviting}
        onOpenChange={setInviting}
        onCreated={invited}
        onStale={reloadGroups}
      />
      <AccessDialog
        user={changing}
        groups={groups}
        open={changing !== null}
        onOpenChange={(open) => !open && setChanging(null)}
        onSaved={accessSaved}
        onStale={reloadGroups}
      />
      <DisableDialog
        user={disabling}
        open={disabling !== null}
        onOpenChange={(open) => !open && setDisabling(null)}
        onDone={disabled}
      />
      <InviteLinkDialog link={link?.link ?? null} name={link?.name ?? ""} onDone={() => setLink(null)} />
    </div>
  );
}
