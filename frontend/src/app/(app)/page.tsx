import type { Metadata } from "next";
import { PlaceholderPage } from "@/components/placeholder-page";
import { navItem } from "@/lib/navigation";

export const metadata: Metadata = { title: navItem("/").title };

export default function DashboardPage() {
  return <PlaceholderPage href="/" />;
}
