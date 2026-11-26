import { formatTime } from "@/components/profile/profile-page";
import { CheckCard } from "@/components/servers/checks/check-card";
import { Badge } from "@/components/ui/badge";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { type Container, containerTone, groupContainers, type ServerCheck, TONE_CLASSES } from "@/lib/checks";

/**
 * The server's containers, one table per Compose project. The rows are the last listing, so they stay when a later
 * check fails; their Last seen says how fresh they are.
 */
export function ContainersTab({
  check,
  containers,
  now,
}: {
  check: ServerCheck<"containers">;
  containers: Container[];
  now: Date;
}) {
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
