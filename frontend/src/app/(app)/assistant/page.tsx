import type { Metadata } from "next";
import { PlaceholderPage } from "@/components/placeholder-page";
import { navItem } from "@/lib/navigation";

export const metadata: Metadata = { title: navItem("/assistant").title };

export default function AssistantPage() {
  return <PlaceholderPage href="/assistant" />;
}
