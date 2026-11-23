// @vitest-environment node
import { NextRequest } from "next/server";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { proxy } from "@/proxy";

const fetchMock = vi.fn();

function answer(status: string) {
  fetchMock.mockResolvedValue(
    new Response(JSON.stringify({ status, user: null }), { headers: { "content-type": "application/json" } }),
  );
}

function request(path: string, cookie?: string) {
  return new NextRequest(new URL(path, "http://megoo.test"), { headers: cookie ? { cookie } : undefined });
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

describe("proxy", () => {
  it("sends a signed-out person to the sign-in page, keeping the page they asked for", async () => {
    answer("signed_out");
    const response = await proxy(request("/servers"));
    expect(response.status).toBe(307);
    expect(response.headers.get("location")).toBe("http://megoo.test/login?next=%2Fservers");
  });

  it("lets an active session through", async () => {
    answer("active");
    const response = await proxy(request("/servers", "megoo_session=tok"));
    expect(response.headers.get("location")).toBeNull();
    expect(response.headers.get("x-middleware-next")).toBe("1");
  });

  it("sends an active session away from the sign-in page", async () => {
    answer("active");
    const response = await proxy(request("/login", "megoo_session=tok"));
    expect(response.headers.get("location")).toBe("http://megoo.test/");
  });

  it("sends everyone to setup before the Owner exists", async () => {
    answer("setup_required");
    const response = await proxy(request("/servers"));
    expect(response.headers.get("location")).toBe("http://megoo.test/setup");
  });

  it("counts a backend that does not answer as signed out", async () => {
    fetchMock.mockRejectedValue(new TypeError("fetch failed"));
    const response = await proxy(request("/"));
    expect(response.headers.get("location")).toBe("http://megoo.test/login");
  });

  it("asks the backend about the request's session cookie", async () => {
    answer("active");
    await proxy(request("/", "sidebar_state=false; megoo_session=tok"));
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("http://backend:8000/api/auth/session");
    expect(init.headers).toEqual({ cookie: "megoo_session=tok" });
  });
});
