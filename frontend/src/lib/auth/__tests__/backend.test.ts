// @vitest-environment node
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { backendUrl, fetchSession, SESSION_COOKIE } from "@/lib/auth/backend";

const fetchMock = vi.fn();

function answer(body: unknown, status = 200) {
  fetchMock.mockResolvedValue(new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } }));
}

beforeEach(() => {
  vi.stubGlobal("fetch", fetchMock);
  vi.stubEnv("BACKEND_URL", "http://backend:8000");
});

afterEach(() => {
  fetchMock.mockReset();
  vi.unstubAllGlobals();
  vi.unstubAllEnvs();
});

describe("backendUrl", () => {
  it("comes from BACKEND_URL, else localhost", () => {
    expect(backendUrl()).toBe("http://backend:8000");
    vi.stubEnv("BACKEND_URL", undefined);
    expect(backendUrl()).toBe("http://localhost:8000");
  });
});

describe("fetchSession", () => {
  it("forwards only the session cookie to the backend and returns the session", async () => {
    const session = { status: "active", user: { id: "u1", name: "Ada", email: "ada@example.com", platform_role: "owner" } };
    answer(session);

    await expect(fetchSession("tok")).resolves.toEqual(session);

    expect(SESSION_COOKIE).toBe("megoo_session");
    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("http://backend:8000/api/auth/session");
    expect(init.headers).toEqual({ cookie: "megoo_session=tok" });
    expect(init.cache).toBe("no-store");
    expect(init.signal).toBeInstanceOf(AbortSignal);
  });

  it("sends no cookie header without a token", async () => {
    answer({ status: "signed_out", user: null });

    await expect(fetchSession(undefined)).resolves.toEqual({ status: "signed_out", user: null });

    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(init.headers ?? {}).not.toHaveProperty("cookie");
  });

  it("is null when the fetch throws", async () => {
    fetchMock.mockRejectedValue(new TypeError("fetch failed"));
    await expect(fetchSession("tok")).resolves.toBeNull();
  });

  it("is null on a 500", async () => {
    answer({ status: "active", user: null }, 500);
    await expect(fetchSession("tok")).resolves.toBeNull();
  });

  it("is null when the body has no status", async () => {
    answer({ user: null });
    await expect(fetchSession("tok")).resolves.toBeNull();
  });

  it("is null when the body is not JSON", async () => {
    fetchMock.mockResolvedValue(new Response("<html>", { status: 200 }));
    await expect(fetchSession("tok")).resolves.toBeNull();
  });
});
