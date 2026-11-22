import type { Metadata } from "next";
import { PlaceholderPage } from "@/components/placeholder-page";
import { navItem } from "@/lib/navigation";

export const metadata: Metadata = { title: navItem("/reports").title };

export default function ReportsPage() {
  return <PlaceholderPage href="/reports" />;
}
