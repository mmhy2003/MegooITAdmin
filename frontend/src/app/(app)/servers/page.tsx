import type { Metadata } from "next";
import { PlaceholderPage } from "@/components/placeholder-page";
import { navItem } from "@/lib/navigation";

export const metadata: Metadata = { title: navItem("/servers").title };

export default function ServersPage() {
  return <PlaceholderPage href="/servers" />;
}
