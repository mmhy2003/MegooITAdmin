import type { SessionInfo } from "@/lib/auth/gate";

/** The name of the backend's HTTP-only session cookie. */
export const SESSION_COOKIE = "megoo_session";

/** The backend's base URL, as seen from the Next.js server. */
export function backendUrl(): string {
  return process.env.BACKEND_URL ?? "http://localhost:8000";
}

/** Asks the backend about the session of `token`; null when it does not answer or answers badly. */
export async function fetchSession(token: string | undefined): Promise<SessionInfo | null> {
  try {
    const response = await fetch(`${backendUrl()}/api/auth/session`, {
      headers: token ? { cookie: `${SESSION_COOKIE}=${token}` } : undefined,
      cache: "no-store",
      signal: AbortSignal.timeout(3000),
    });
    if (!response.ok) return null;
    const body: unknown = await response.json();
    if (typeof body !== "object" || body === null || typeof (body as SessionInfo).status !== "string") return null;
    return body as SessionInfo;
  } catch {
    return null;
  }
}
