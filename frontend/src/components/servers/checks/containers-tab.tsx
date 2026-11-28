import Link from "next/link";
import { formatTime } from "@/components/profile/profile-page";
import { CheckCard } from "@/components/servers/checks/check-card";
import { Badge } from "@/components/ui/badge";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { type Container, containerTone, groupContainers, type ServerCheck, TONE_CLASSES } from "@/lib/checks";
import { encodeSource } from "@/lib/logs/sources";

/** The server's Logs tab, following one container's logs. */
function logsOf(serverId: string, item: Container): string {
  const src = encodeSource({ kind: "container", server_id: serverId, container_id: item.container_id, name: item.name });
  return `/servers/${serverId}?tab=logs&src=${encodeURIComponent(src)}`;
}

/**
 * The server's containers, one table per Compose project. The rows are the last listing, so they stay when a later
 * check fails; their Last seen says how fresh they are. With View logs, each row links to its logs on the Logs tab.
 */
export function ContainersTab({
  check,
  containers,
  now,
  serverId,
  canViewLogs = false,
}: {
  check: ServerCheck<"containers">;
  containers: Container[];
  now: Date;
  serverId?: string;
  canViewLogs?: boolean;
}) {
  const logs = canViewLogs && serverId !== undefined ? serverId : null;
  return (
    <CheckCard title="Containers" check={check} now={now} always>
      {containers.length > 0 ? (
        <div className="space-y-6">
          {groupContainers(containers).map((group) => (
            <section key={group.project ?? ""} className="space-y-2">
              <h3 className="font-medium">{group.project ?? "No Compose project"}</h3>
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Name</TableHead>
                    <TableHead>Service</TableHead>
                    <TableHead>Image</TableHead>
                    <TableHead>State</TableHead>
                    <TableHead>Status</TableHead>
                    <TableHead>Last seen</TableHead>
                    {logs !== null && <TableHead><span className="sr-only">Logs</span></TableHead>}
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {group.containers.map((item) => (
                    <TableRow key={item.container_id}>
                      <TableCell className="font-mono">{item.name}</TableCell>
                      <TableCell>{item.compose_service}</TableCell>
                      <TableCell className="font-mono">{item.image}</TableCell>
                      <TableCell>
                        <Badge variant="outline" className={TONE_CLASSES[containerTone(item.state)]}>
                          {item.state}
                        </Badge>
                      </TableCell>
                      <TableCell>{item.status}</TableCell>
                      <TableCell>{formatTime(item.last_seen_at)}</TableCell>
                      {logs !== null && (
                        <TableCell>
                          <Link href={logsOf(logs, item)} className="text-primary underline-offset-4 hover:underline">
                            Logs
                          </Link>
                        </TableCell>
                      )}
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </section>
          ))}
        </div>
      ) : (
        check.status === "ok" && <p>No containers on this server.</p>
      )}
    </CheckCard>
  );
}
