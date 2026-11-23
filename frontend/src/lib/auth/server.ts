import { cookies } from "next/headers";
import { redirect } from "next/navigation";
import { cache } from "react";
import { fetchSession, SESSION_COOKIE } from "@/lib/auth/backend";
import type { SessionInfo, SessionUser } from "@/lib/auth/gate";

/** The session of this request, asked of the backend once per render (server components only). */
export const getSession = cache(
  async (): Promise<SessionInfo | null> => fetchSession((await cookies()).get(SESSION_COOKIE)?.value),
);

/** The signed-in user; anyone else is sent to the sign-in page. */
export async function requireUser(): Promise<SessionUser> {
  const session = await getSession();
  if (session?.status !== "active" || !session.user) redirect("/login");
  return session.user;
}
