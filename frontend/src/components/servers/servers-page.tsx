"use client";

import { MoreHorizontal, Plus } from "lucide-react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { RemoveServerDialog } from "@/components/servers/remove-server-dialog";
import { ServerDialog } from "@/components/servers/server-dialog";
import { ServerFilters } from "@/components/servers/server-filters";
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
import type { ServerGroup } from "@/lib/access";
import { ApiError, apiFetch } from "@/lib/api";
import { messageFor } from "@/lib/auth/messages";
import {
  addressOf,
  filtersFrom,
  listPath,
  OS_LABELS,
  type Server,
  type ServerFilters as Filters,
} from "@/lib/servers";

type Lists = { groups: ServerGroup[]; tags: string[]; servers: Server[] };

/** The Servers page: the servers the person sees, filtered by the group and tags in the address. */
export function ServersPage() {
  const router = useRouter();
  const filters = filtersFrom(useSearchParams());
  const path = listPath(filters);
  const [lists, setLists] = useState<Lists | null>(null);
  const [error, setError] = useState<string | null>(null);
  // `undefined` is closed, `null` is a new server.
  const [editing, setEditing] = useState<Server | null | undefined>(undefined);
  const [removing, setRemoving] = useState<Server | null>(null);

  const reload = useCallback(
    () =>
      Promise.all([
        apiFetch<ServerGroup[]>("/server-groups"),
        apiFetch<string[]>("/server-tags"),
        apiFetch<Server[]>(path),
      ]).then(
        ([groups, tags, servers]) => {
          setLists({ groups, tags, servers });
          setError(null);
        },
        (e: unknown) => setError(e instanceof ApiError ? e.detail : "error"),
      ),
    [path],
  );

  useEffect(() => {
    void reload();
  }, [reload]);

  function choose(next: Filters) {
    router.replace(addressOf(next));
  }

  function saved() {
    setEditing(undefined);
    void reload();
  }

  function removed() {
    setRemoving(null);
    void reload();
  }

  const manageable = lists ? lists.groups.filter((g) => g.can_manage) : [];
  const filtered = filters.group !== null || filters.tags.length > 0;
  const defaultGroupId = manageable.some((g) => g.id === filters.group) ? filters.group : null;

  return (
    <div className="space-y-6">
      {error && <Alert variant="destructive">{messageFor(error)}</Alert>}
      <Card>
        <CardHeader>
          <CardTitle>
            <h2>Servers</h2>
          </CardTitle>
          {manageable.length > 0 && (
            <CardAction>
              <Button onClick={() => setEditing(null)}>
                <Plus aria-hidden />
                Register server
              </Button>
            </CardAction>
          )}
        </CardHeader>
        {lists && (
          <CardContent className="space-y-4">
            {lists.groups.length === 0 ? (
              <p className="text-muted-foreground">
                You do not see any server group yet. Ask the Owner of this installation for a role.
              </p>
            ) : (
              <>
                <ServerFilters groups={lists.groups} tags={lists.tags} filters={filters} onChange={choose} />
                {lists.servers.length === 0 ? (
                  <Empty
                    filtered={filtered}
                    canManage={manageable.length > 0}
                    onClear={() => router.replace("/servers")}
                  />
                ) : (
                  <ServerTable servers={lists.servers} onEdit={setEditing} onRemove={setRemoving} />
                )}
              </>
            )}
          </CardContent>
        )}
      </Card>
      <ServerDialog
        server={editing ?? null}
        groups={manageable}
        defaultGroupId={defaultGroupId}
        tags={lists?.tags ?? []}
        open={editing !== undefined}
        onOpenChange={(open) => !open && setEditing(undefined)}
        onSaved={saved}
        onStale={() => void reload()}
      />
      <RemoveServerDialog
        server={removing}
        open={removing !== null}
        onOpenChange={(open) => !open && setRemoving(null)}
        onRemoved={removed}
      />
    </div>
  );
}

function Empty({ filtered, canManage, onClear }: { filtered: boolean; canManage: boolean; onClear: () => void }) {
  if (filtered) {
    return (
      <div className="space-y-2">
        <p className="text-muted-foreground">No server matches these filters.</p>
        <Button variant="outline" onClick={onClear}>
          Clear filters
        </Button>
      </div>
    );
  }
  return (
    <div className="space-y-1">
      <p className="font-medium">No servers yet.</p>
      <p className="text-muted-foreground">
        {canManage
          ? "Register the first one with Register server."
          : "Nobody has registered a server in your groups yet."}
      </p>
    </div>
  );
}

type TableProps = {
  servers: Server[];
  onEdit: (server: Server) => void;
  onRemove: (server: Server) => void;
};

function ServerTable({ servers, onEdit, onRemove }: TableProps) {
  return (
    <div className="overflow-x-auto">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Name</TableHead>
            <TableHead>Address</TableHead>
            <TableHead>Group</TableHead>
            <TableHead>OS</TableHead>
            <TableHead>Role</TableHead>
            <TableHead>Tags</TableHead>
            <TableHead>
              <span className="sr-only">Actions</span>
            </TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {servers.map((server) => (
            <TableRow key={server.id}>
              <TableCell className="font-medium">
                <Link href={`/servers/${server.id}`} className="hover:underline">
                  {server.name}
                </Link>
              </TableCell>
              <TableCell className="font-mono">{`${server.address}:${server.port}`}</TableCell>
              <TableCell>{server.group_name}</TableCell>
              <TableCell>{OS_LABELS[server.os]}</TableCell>
              <TableCell>{server.role}</TableCell>
              <TableCell>
                <div className="flex flex-wrap gap-1">
                  {server.tags.map((tag) => (
                    <Badge key={tag} variant="secondary">
                      {tag}
                    </Badge>
                  ))}
                </div>
              </TableCell>
              <TableCell className="text-right">
                {server.can_manage && (
                  <DropdownMenu>
                    <DropdownMenuTrigger asChild>
                      <Button variant="ghost" size="icon" aria-label={`Actions for ${server.name}`}>
                        <MoreHorizontal aria-hidden />
                      </Button>
                    </DropdownMenuTrigger>
                    <DropdownMenuContent align="end">
                      <DropdownMenuItem onSelect={() => onEdit(server)}>Edit</DropdownMenuItem>
                      <DropdownMenuItem onSelect={() => onRemove(server)}>Remove</DropdownMenuItem>
                    </DropdownMenuContent>
                  </DropdownMenu>
                )}
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}
