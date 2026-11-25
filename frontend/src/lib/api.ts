import { goTo } from "@/lib/auth/navigate";

/** A refused or failed API call: the HTTP status (0 when the server did not answer) and the reason. */
export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly detail: string,
  ) {
    super(`${status} ${detail}`);
    this.name = "ApiError";
  }
}

/** The pages where a person is not signed in yet, so a signed-out answer must not send them to sign-in. */
const SIGN_IN_PAGES = ["/login", "/setup", "/invite"];

/**
 * Calls `/api${path}` from the browser and returns its JSON (undefined on a 204).
 * A body is sent as JSON, with POST unless another method is given. A refusal throws `ApiError`.
 * A signed-out answer outside the sign-in pages also sends the person to sign-in.
 * `background` marks an automatic re-read: the backend does not count it as activity, so it never keeps an idle
 * session alive.
 */
export async function apiFetch<T>(
  path: string,
  options: { method?: string; body?: unknown; background?: boolean } = {},
): Promise<T> {
  const { body } = options;
  const hasBody = body !== undefined;
  const headers: Record<string, string> = {};
  if (hasBody) headers["content-type"] = "application/json";
  if (options.background) headers["x-megoo-background"] = "1";
  let response: Response;
  try {
    response = await fetch(`/api${path}`, {
      method: options.method ?? (hasBody ? "POST" : "GET"),
      credentials: "same-origin",
      headers: Object.keys(headers).length > 0 ? headers : undefined,
      body: hasBody ? JSON.stringify(body) : undefined,
    });
  } catch {
    throw new ApiError(0, "unreachable");
  }
  if (response.status === 204) return undefined as T;
  const json: unknown = await response.json().catch(() => null);
  if (response.ok) return json as T;

  const raw = (json as { detail?: unknown } | null)?.detail;
  const detail = typeof raw === "string" ? raw : "invalid";
  const { pathname, search } = window.location;
  if (response.status === 401 && detail === "not_signed_in" && !SIGN_IN_PAGES.includes(pathname)) {
    goTo("/login?next=" + encodeURIComponent(pathname + search));
  }
  throw new ApiError(response.status, detail);
}
