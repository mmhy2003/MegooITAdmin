import type { Metadata } from "next";
import { PlaceholderPage } from "@/components/placeholder-page";
import { navItem } from "@/lib/navigation";

export const metadata: Metadata = { title: navItem("/knowledge-base").title };

export default function KnowledgeBasePage() {
  return <PlaceholderPage href="/knowledge-base" />;
}
