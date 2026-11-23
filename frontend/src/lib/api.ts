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

/**
 * Calls `/api${path}` from the browser and returns its JSON (undefined on a 204).
 * A body is sent as JSON, with POST unless another method is given. A refusal throws `ApiError`.
 * A signed-out answer outside the sign-in pages also sends the person to sign-in.
 */
export async function apiFetch<T>(path: string, options: { method?: string; body?: unknown } = {}): Promise<T> {
  const { body } = options;
  const hasBody = body !== undefined;
  let response: Response;
  try {
    response = await fetch(`/api${path}`, {
      method: options.method ?? (hasBody ? "POST" : "GET"),
      credentials: "same-origin",
      headers: hasBody ? { "content-type": "application/json" } : undefined,
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
  if (response.status === 401 && detail === "not_signed_in" && pathname !== "/login" && pathname !== "/setup") {
    goTo("/login?next=" + encodeURIComponent(pathname + search));
  }
  throw new ApiError(response.status, detail);
}
