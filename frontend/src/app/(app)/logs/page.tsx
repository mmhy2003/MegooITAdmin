import type { Metadata } from "next";
import { PlaceholderPage } from "@/components/placeholder-page";
import { navItem } from "@/lib/navigation";

export const metadata: Metadata = { title: navItem("/logs").title };

export default function LogsPage() {
  return <PlaceholderPage href="/logs" />;
}
