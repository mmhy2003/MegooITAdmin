import type { Metadata } from "next";
import { UsersPage } from "@/components/settings/users-page";
import { requireUser } from "@/lib/auth/server";

export const metadata: Metadata = { title: "Users" };

export default async function UsersRoute() {
  return <UsersPage currentUserId={(await requireUser()).id} />;
}
