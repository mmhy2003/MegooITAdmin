"use client";

import { Pencil, Plus, Trash2 } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { DeleteGroupDialog } from "@/components/settings/delete-group-dialog";
import { GroupDialog } from "@/components/settings/group-dialog";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardAction, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import type { ServerGroup, UserRow } from "@/lib/access";
import { ApiError, apiFetch } from "@/lib/api";
import { messageFor } from "@/lib/auth/messages";

/** The Server groups tab of Settings: every group, how many people hold a role in it, how many servers it holds, and the Owner's changes. */
export function GroupsPage() {
  const [groups, setGroups] = useState<ServerGroup[] | null>(null);
  const [users, setUsers] = useState<UserRow[]>([]);
  const [error, setError] = useState<string | null>(null);
  // `undefined` is closed, `null` is a new group.
  const [editing, setEditing] = useState<ServerGroup | null | undefined>(undefined);
  const [deleting, setDeleting] = useState<ServerGroup | null>(null);

  const reload = useCallback(
    () =>
      Promise.all([apiFetch<ServerGroup[]>("/server-groups"), apiFetch<UserRow[]>("/users")]).then(
        ([serverGroups, people]) => {
          setGroups(serverGroups);
          setUsers(people);
          setError(null);
        },
        (e: unknown) => setError(e instanceof ApiError ? e.detail : "error"),
      ),
    [],
  );

  useEffect(() => {
    void reload();
  }, [reload]);

  function saved() {
    setEditing(undefined);
    void reload();
  }

  function deleted() {
    setDeleting(null);
    void reload();
  }

  const people = deleting
    ? users.filter((u) => u.grants.some((g) => g.group_id === deleting.id)).map((u) => u.name)
    : [];

  return (
    <div className="space-y-6">
      {error && <Alert variant="destructive">{messageFor(error)}</Alert>}
      <Card>
        <CardHeader>
          <CardTitle>
            <h2>Server groups</h2>
          </CardTitle>
          <CardAction>
            <Button onClick={() => setEditing(null)}>
              <Plus aria-hidden />
              New group
            </Button>
          </CardAction>
        </CardHeader>
        <CardContent>
          {groups && (
            <div className="overflow-x-auto">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Name</TableHead>
                    <TableHead>Description</TableHead>
                    <TableHead>People</TableHead>
                    <TableHead>Servers</TableHead>
                    <TableHead>
                      <span className="sr-only">Actions</span>
                    </TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {groups.map((group) => (
                    <TableRow key={group.id}>
                      <TableCell className="font-medium">{group.name}</TableCell>
                      <TableCell className="text-muted-foreground">{group.description}</TableCell>
                      <TableCell>{group.member_count ?? 0}</TableCell>
                      <TableCell>{group.server_count}</TableCell>
                      <TableCell className="text-right">
                        <Button
                          variant="ghost"
                          size="icon"
                          aria-label={`Edit ${group.name}`}
                          onClick={() => setEditing(group)}
                        >
                          <Pencil aria-hidden />
                        </Button>
                        <Button
                          variant="ghost"
                          size="icon"
                          aria-label={`Delete ${group.name}`}
                          onClick={() => setDeleting(group)}
                        >
                          <Trash2 aria-hidden />
                        </Button>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          )}
        </CardContent>
      </Card>
      <GroupDialog
        group={editing}
        open={editing !== undefined}
        onOpenChange={(open) => !open && setEditing(undefined)}
        onSaved={saved}
      />
      <DeleteGroupDialog
        group={deleting}
        people={people}
        open={deleting !== null}
        onOpenChange={(open) => !open && setDeleting(null)}
        onDeleted={deleted}
      />
    </div>
  );
}
