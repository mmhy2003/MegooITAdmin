import type { Metadata } from "next";
import { PlaceholderPage } from "@/components/placeholder-page";
import { navItem } from "@/lib/navigation";

export const metadata: Metadata = { title: navItem("/secrets").title };

export default function SecretsPage() {
  return <PlaceholderPage href="/secrets" />;
}
