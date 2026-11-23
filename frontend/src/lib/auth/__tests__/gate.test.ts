import { describe, expect, it } from "vitest";
import { type AuthStatus, gateRedirect, safeNext } from "@/lib/auth/gate";

describe("gateRedirect", () => {
  it.each<[AuthStatus | null, string, string, string | null]>([
    [null, "/servers", "", "/login?next=%2Fservers"],
    [null, "/login", "", null],
    [null, "/", "", "/login"],
    ["signed_out", "/", "", "/login"],
    ["signed_out", "/login", "", null],
    ["signed_out", "/servers", "", "/login?next=%2Fservers"],
    ["signed_out", "/servers", "?tag=web", "/login?next=%2Fservers%3Ftag%3Dweb"],
    ["signed_out", "/setup", "", "/login?next=%2Fsetup"],
    ["mfa_required", "/login", "", null],
    ["mfa_required", "/", "", "/login"],
    ["mfa_required", "/audit", "", "/login?next=%2Faudit"],
    ["enrolment_required", "/login", "", null],
    ["enrolment_required", "/profile", "", "/login?next=%2Fprofile"],
    ["active", "/login", "", "/"],
    ["active", "/setup", "", "/"],
    ["active", "/servers", "", null],
    ["active", "/", "", null],
    ["setup_required", "/login", "", "/setup"],
    ["setup_required", "/", "", "/setup"],
    ["setup_required", "/setup", "", null],
    [null, "/invite", "", null],
    ["signed_out", "/invite", "", null],
    ["mfa_required", "/invite", "", null],
    ["active", "/invite", "", null],
    ["setup_required", "/invite", "", "/setup"],
  ])("(%s, %s, %j) → %s", (status, pathname, search, expected) => {
    expect(gateRedirect(status, pathname, search)).toBe(expected);
  });

  it("defaults the search to empty", () => {
    expect(gateRedirect("signed_out", "/servers")).toBe("/login?next=%2Fservers");
  });
});

describe("safeNext", () => {
  it("keeps a local path", () => {
    expect(safeNext("/servers")).toBe("/servers");
    expect(safeNext("/servers?tag=web")).toBe("/servers?tag=web");
  });

  it("keeps the hash of a local path", () => {
    expect(safeNext("/servers?tag=web#top")).toBe("/servers?tag=web#top");
  });

  it.each([
    "//evil.example",
    "/\\evil",
    "https://x",
    "/\t/evil.example",
    "/\n/evil.example",
    "/\r/evil.example",
    "\t//evil.example",
    "/servers\\..\\",
    "",
    undefined,
    null,
  ])("refuses %j", (next) => {
    expect(safeNext(next)).toBeNull();
  });
});
