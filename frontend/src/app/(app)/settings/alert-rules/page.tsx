import type { Metadata } from "next";
import { AlertRulesPage } from "@/components/settings/alert-rules-page";

export const metadata: Metadata = { title: "Alert rules" };

export default function AlertRulesRoute() {
  return <AlertRulesPage />;
}
