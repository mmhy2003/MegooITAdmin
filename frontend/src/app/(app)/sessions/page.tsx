import type { Metadata } from "next";
import { PlaceholderPage } from "@/components/placeholder-page";
import { navItem } from "@/lib/navigation";

export const metadata: Metadata = { title: navItem("/sessions").title };

export default function SessionsPage() {
  return <PlaceholderPage href="/sessions" />;
}
