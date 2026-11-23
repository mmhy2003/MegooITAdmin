import type { Metadata } from "next";
import { redirect } from "next/navigation";
import { SetupFlow } from "@/components/auth/setup-flow";
import { getSession } from "@/lib/auth/server";

export const metadata: Metadata = { title: "Set up MegooITAdmin" };

export default async function SetupPage() {
  const status = (await getSession())?.status;
  // Once an Owner exists, the setup page is closed.
  if (status && status !== "setup_required") redirect("/login");
  return <SetupFlow />;
}
