import type { Metadata } from "next";
import { PlaceholderPage } from "@/components/placeholder-page";
import { navItem } from "@/lib/navigation";

export const metadata: Metadata = { title: navItem("/playbooks").title };

export default function PlaybooksPage() {
  return <PlaceholderPage href="/playbooks" />;
}
