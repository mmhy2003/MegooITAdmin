import type { Metadata } from "next";
import { Suspense } from "react";
import { DashboardPage } from "@/components/dashboard/dashboard-page";
import { navItem } from "@/lib/navigation";

export const metadata: Metadata = { title: navItem("/").title };

export default function DashboardRoute() {
  return (
    <Suspense>
      <DashboardPage />
    </Suspense>
  );
}
