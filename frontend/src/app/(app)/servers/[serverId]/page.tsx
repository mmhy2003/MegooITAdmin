import type { Metadata } from "next";
import { Suspense } from "react";
import { ServerPage } from "@/components/servers/server-page";
import { navItem } from "@/lib/navigation";

export const metadata: Metadata = { title: navItem("/servers").title };

export default async function ServerRoute({ params }: { params: Promise<{ serverId: string }> }) {
  const { serverId } = await params;
  return (
    <Suspense>
      <ServerPage serverId={serverId} />
    </Suspense>
  );
}
