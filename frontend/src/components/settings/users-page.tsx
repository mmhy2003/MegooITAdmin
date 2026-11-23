"use client";

import { MoreHorizontal, UserPlus } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { formatTime } from "@/components/profile/profile-page";
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

  return (
    <div className="space-y-6">
      {error && <Alert variant="destructive">{messageFor(error)}</Alert>}
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
                                <DropdownMenuItem key={action}>{action}</DropdownMenuItem>
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
      <InviteDialog groups={groups} open={inviting} onOpenChange={setInviting} onCreated={invited} />
      <InviteLinkDialog link={link?.link ?? null} name={link?.name ?? ""} onDone={() => setLink(null)} />
    </div>
  );
}
