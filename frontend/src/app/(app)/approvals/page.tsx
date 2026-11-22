import type { Metadata } from "next";
import { PlaceholderPage } from "@/components/placeholder-page";
import { navItem } from "@/lib/navigation";

export const metadata: Metadata = { title: navItem("/approvals").title };

export default function ApprovalsPage() {
  return <PlaceholderPage href="/approvals" />;
}
