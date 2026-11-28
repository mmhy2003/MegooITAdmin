import { describe, expect, it } from "vitest";
import { checkPattern, matches } from "@/lib/logs/allowlist";

// The cases of backend/tests/logs/test_log_allowlist_rules.py, one to one.
describe("matches", () => {
  it("never lets a wildcard cross a slash", () => {
    expect(matches("/var/log/nginx/access.log", ["/var/log/*.log"])).toBe(false);
    expect(matches("/var/log/nginx/access.log", ["/var/log/nginx/*.log"])).toBe(true);
  });

  it("lets a question mark match one character", () => {
    expect(matches("/var/log/app1.log", ["/var/log/app?.log"])).toBe(true);
    expect(matches("/var/log/app12.log", ["/var/log/app?.log"])).toBe(false);
    expect(matches("/var/log/app/.log", ["/var/log/app?.log"])).toBe(false);
  });

  it("lets other characters match only themselves", () => {
    expect(matches("/var/log/aXlog", ["/var/log/a.log"])).toBe(false);
    expect(matches("/var/log/+x", ["/var/log/+x"])).toBe(true);
    expect(matches("/var/log/x", ["/var/log/+x"])).toBe(false);
    expect(matches("/var/log/++x", ["/var/log/+x"])).toBe(false);
  });

  it("needs the whole path to match", () => {
    expect(matches("/var/log/syslog.1", ["/var/log/syslog"])).toBe(false);
    expect(matches("/old/var/log/syslog", ["/var/log/syslog"])).toBe(false);
    expect(matches("/var/log/syslog", ["/var/log/messages", "/var/log/syslog"])).toBe(true);
  });

  it("matches nothing without a pattern", () => {
    expect(matches("/var/log/syslog", [])).toBe(false);
  });

  it("matches many stars in linear time", () => {
    // As a regex, "[^/]*" per star backtracks exponentially on this path; the glob match does not.
    const pattern = "/v/" + "*a".repeat(20) + "*b";
    expect(checkPattern(pattern)).toBe(true);
    const started = performance.now();
    expect(matches("/v/" + "a".repeat(250), [pattern])).toBe(false);
    expect(matches("/v/" + "a".repeat(250) + "b", [pattern])).toBe(true);
    expect(performance.now() - started).toBeLessThan(500);
  });
});

describe("checkPattern", () => {
  it.each(["/*", "/v*r/log", "var/log", "/var/../etc", "/var//x", "/var/log/", "/var/log/[ab]", "/" + "a".repeat(255)])(
    "refuses %s",
    (pattern) => {
      expect(checkPattern(pattern)).toBe(false);
    },
  );

  it.each(["/var/log/syslog", "/var/log/messages", "/var/log/nginx/*.log", "/var/log/apache2/*.log"])(
    "accepts the starter pattern %s",
    (pattern) => {
      expect(checkPattern(pattern)).toBe(true);
    },
  );
});
