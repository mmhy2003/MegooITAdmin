/** Where a person stands in the sign-in flow, as `/api/auth/session` reports it. */
export type AuthStatus = "setup_required" | "signed_out" | "mfa_required" | "enrolment_required" | "active";

/** The signed-in person, as `/api/auth/session` reports them. */
export type SessionUser = { id: string; name: string; email: string; is_owner: boolean };

/** The body of `/api/auth/session`. */
export type SessionInfo = { status: AuthStatus; user: SessionUser | null };

const PROBE_ORIGIN = "https://megooitadmin.invalid";

/**
 * `next` when it is a path on this site, else null, so a link cannot send a person elsewhere after sign-in.
 * Browsers drop tabs and newlines and read `\` as `/`, so `/\t/evil.example` would leave the site: such values
 * are refused, and what is left must resolve to this site's origin.
 */
export function safeNext(next: string | null | undefined): string | null {
  if (!next || !next.startsWith("/") || /[\u0000-\u001f\u007f\\]/.test(next)) return null;
  let url: URL;
  try {
    url = new URL(next, PROBE_ORIGIN);
  } catch {
    return null;
  }
  if (url.origin !== PROBE_ORIGIN) return null;
  return url.pathname + url.search + url.hash;
}

/**
 * The page a request for `pathname` must go to instead, or null to let it through.
 * A null status means the backend did not answer, and counts as signed out.
 */
export function gateRedirect(status: AuthStatus | null, pathname: string, search = ""): string | null {
  switch (status) {
    case "setup_required":
      return pathname === "/setup" ? null : "/setup";
    case "active":
      return pathname === "/login" || pathname === "/setup" ? "/" : null;
    default:
      if (pathname === "/login") return null;
      if (pathname === "/") return "/login";
      return "/login?next=" + encodeURIComponent(pathname + search);
  }
}
