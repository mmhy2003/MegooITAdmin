import type { Metadata } from "next";
import { PlaceholderPage } from "@/components/placeholder-page";
import { navItem } from "@/lib/navigation";

export const metadata: Metadata = { title: navItem("/scheduler").title };

export default function SchedulerPage() {
  return <PlaceholderPage href="/scheduler" />;
}
