import type { Metadata } from "next";
import { PlaceholderPage } from "@/components/placeholder-page";
import { navItem } from "@/lib/navigation";

export const metadata: Metadata = { title: navItem("/audit").title };

export default function AuditPage() {
  return <PlaceholderPage href="/audit" />;
}
