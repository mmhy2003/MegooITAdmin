import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError, apiFetch } from "@/lib/api";
import { goTo } from "@/lib/auth/navigate";

vi.mock("@/lib/auth/navigate", () => ({ goTo: vi.fn() }));

const fetchMock = vi.fn();

function answer(body: unknown, status = 200) {
  fetchMock.mockResolvedValue(new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } }));
}

async function failure(promise: Promise<unknown>): Promise<ApiError> {
  const error = await promise.then(() => null, (e: unknown) => e);
  expect(error).toBeInstanceOf(ApiError);
  return error as ApiError;
}

beforeEach(() => {
  vi.stubGlobal("fetch", fetchMock);
  window.history.pushState({}, "", "/");
});

afterEach(() => {
  fetchMock.mockReset();
  vi.mocked(goTo).mockReset();
  vi.unstubAllGlobals();
});

describe("apiFetch", () => {
  it("sends JSON with its content type and returns JSON", async () => {
    answer({ status: "mfa_required" });

    await expect(apiFetch("/auth/login", { body: { email: "a@b.c", password: "pw" } })).resolves.toEqual({ status: "mfa_required" });

    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("/api/auth/login");
    expect(init.method).toBe("POST");
    expect(init.credentials).toBe("same-origin");
    expect(init.headers).toEqual({ "content-type": "application/json" });
    expect(init.body).toBe(JSON.stringify({ email: "a@b.c", password: "pw" }));
  });

  it("uses GET without a body, and the given method otherwise", async () => {
    answer({ sessions: [] });
    await apiFetch("/auth/sessions");
    expect((fetchMock.mock.calls[0] as [string, RequestInit])[1].method).toBe("GET");

    answer({});
    await apiFetch("/auth/sessions/s1", { method: "DELETE" });
    expect((fetchMock.mock.calls[1] as [string, RequestInit])[1].method).toBe("DELETE");
  });

  it("marks a background request with X-Megoo-Background", async () => {
    answer([]);
    await apiFetch("/servers", { background: true });

    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(init.headers).toEqual({ "x-megoo-background": "1" });
    expect(init.method).toBe("GET");
  });

  it("sends no background header otherwise", async () => {
    answer([]);
    await apiFetch("/servers");

    expect((fetchMock.mock.calls[0] as [string, RequestInit])[1].headers).toBeUndefined();
  });

  it("keeps the content type beside the background header", async () => {
    answer({});
    await apiFetch("/x", { body: {}, background: true });

    expect((fetchMock.mock.calls[0] as [string, RequestInit])[1].headers).toEqual({
      "content-type": "application/json",
      "x-megoo-background": "1",
    });
  });

  it("returns undefined on a 204", async () => {
    fetchMock.mockResolvedValue(new Response(null, { status: 204 }));
    await expect(apiFetch("/auth/logout", { method: "POST" })).resolves.toBeUndefined();
  });

  it("throws an ApiError with the detail", async () => {
    answer({ detail: "invalid_credentials" }, 401);
    const error = await failure(apiFetch("/auth/login", { body: {} }));
    expect(error.status).toBe(401);
    expect(error.detail).toBe("invalid_credentials");
  });

  it("turns a list detail into invalid", async () => {
    answer({ detail: [{ loc: ["body", "email"], msg: "field required" }] }, 422);
    const error = await failure(apiFetch("/auth/login", { body: {} }));
    expect(error.status).toBe(422);
    expect(error.detail).toBe("invalid");
  });

  it("turns a failed fetch into ApiError(0, unreachable)", async () => {
    fetchMock.mockRejectedValue(new TypeError("Failed to fetch"));
    const error = await failure(apiFetch("/auth/session"));
    expect(error.status).toBe(0);
    expect(error.detail).toBe("unreachable");
  });

  it("sends a signed-out person to sign-in, keeping the page in next", async () => {
    window.history.pushState({}, "", "/servers");
    answer({ detail: "not_signed_in" }, 401);

    const error = await failure(apiFetch("/servers"));

    expect(error.detail).toBe("not_signed_in");
    expect(goTo).toHaveBeenCalledWith("/login?next=%2Fservers");
  });

  it.each(["/login", "/setup", "/invite"])("does not redirect on %s", async (path) => {
    window.history.pushState({}, "", path);
    answer({ detail: "not_signed_in" }, 401);

    await failure(apiFetch("/auth/login/mfa", { body: { code: "123456" } }));

    expect(goTo).not.toHaveBeenCalled();
  });
});
