import type { Metadata } from "next";
import { redirect } from "next/navigation";
import { InviteFlow, InviteSignedIn } from "@/components/auth/invite-flow";
import { getSession } from "@/lib/auth/server";

export const metadata: Metadata = { title: "Accept your invite" };

export default async function InvitePage() {
  const session = await getSession();
  // A half-done sign-in or enrolment carries on at the sign-in page.
  if (session?.status === "mfa_required" || session?.status === "enrolment_required") redirect("/login");
  if (session?.status === "active" && session.user) {
    return <InviteSignedIn name={session.user.name} email={session.user.email} />;
  }
  return <InviteFlow />;
}
