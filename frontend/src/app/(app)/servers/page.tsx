import type { Metadata } from "next";
import { Suspense } from "react";
import { ServersPage } from "@/components/servers/servers-page";
import { navItem } from "@/lib/navigation";

export const metadata: Metadata = { title: navItem("/servers").title };

export default function ServersRoute() {
  return (
    <Suspense>
      <ServersPage />
    </Suspense>
  );
}
