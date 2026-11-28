import type { Metadata } from "next";
import { Suspense } from "react";
import { LogsPage } from "@/components/logs/logs-page";
import { navItem } from "@/lib/navigation";

export const metadata: Metadata = { title: navItem("/logs").title };

export default function LogsRoute() {
  return (
    <Suspense>
      <LogsPage />
    </Suspense>
  );
}
