import { describe, expect, it } from "vitest";
import {
  CONNECTION_REASONS,
  DELIVERY_ERRORS,
  MONITORING_REASONS,
  NOT_CHECKED,
  deliveryErrorText,
  messageFor,
  monitoringText,
  reasonText,
} from "@/lib/auth/messages";
import type { ConnectionReason } from "@/lib/servers";

describe("messageFor", () => {
  it.each([
    ["invalid_credentials", "The email or the password is wrong."],
    ["unreachable", "The server is not answering. Try again in a moment."],
    ["forbidden", "You do not have the rights to do this."],
    ["server_name_taken", "A server with this name exists already."],
    ["group_has_servers", "This group still holds servers. Move or remove them first."],
    ["not_found", "It does not exist, or you cannot see it."],
    ["email_taken", "An account with this email exists already."],
    ["name_taken", "A server group with this name exists already."],
    ["own_account", "You cannot change your own account here."],
    ["last_owner", "At least one enabled Owner must remain."],
    ["invalid_invite", "This invite link does not work. Ask the Owner for a new one."],
    ["already_accepted", "This person has accepted their invite already."],
    ["no_change", "Nothing has changed."],
    ["host_key_pinned", "A host key is pinned already. The page has been reloaded."],
    [
      "stale_host_key",
      "The server's key is no longer the one you compared. It has been fetched again: compare the new fingerprint.",
    ],
    ["host_key_not_changed", "This server's host key has not changed. The page has been reloaded."],
    ["host_key_not_pinned", "Pin the server's host key before testing the connection."],
    ["host_key_changed", "The server's host key has changed. Review it before connecting."],
    ["not_an_ssh_server", "Only Linux servers connect over SSH."],
    ["reason_required", "Say why you accept the new key."],
    ["no_such_reason", "Something went wrong. Try again."],
  ])("%s → %s", (detail, text) => {
    expect(messageFor(detail)).toBe(text);
  });
});

describe("the alert and notification codes", () => {
  const codes = [
    "rule_name_taken",
    "unknown_group",
    "unknown_server",
    "bad_threshold",
    "bad_scope",
    "no_change",
    "channel_name_taken",
    "too_many_channels",
    "webhook_url_https",
    "bad_url",
    "bad_telegram_token",
    "bad_chat_id",
    "email_not_set_up",
  ];

  it.each(codes)("%s has a text of its own", (code) => {
    expect(messageFor(code)).not.toBe(messageFor("no_such_code"));
  });

  it("gives each code another text", () => {
    expect(new Set(codes.map(messageFor)).size).toBe(codes.length);
  });

  it.each([
    ["rule_name_taken", "An alert rule with this name exists already."],
    ["bad_threshold", "The limit does not fit this measure."],
    ["webhook_url_https", "The address must start with https://."],
    ["email_not_set_up", "Set up email first."],
  ])("%s → %s", (code, text) => {
    expect(messageFor(code)).toBe(text);
  });
});

describe("the saved view and log file pattern codes", () => {
  it.each([
    ["view_name_taken", "You have a view with this name already."],
    ["too_many_views", "You have 100 saved views, the most allowed. Delete one first."],
    ["pattern_exists", "This pattern is in the list already."],
    ["too_many_patterns", "This group has 50 patterns, the most allowed. Remove one first."],
  ])("%s → %s", (code, text) => {
    expect(messageFor(code)).toBe(text);
  });
});

describe("deliveryErrorText", () => {
  const codes = [
    "connection_failed",
    "timeout",
    "tls_failed",
    "auth_failed",
    "recipients_refused",
    "smtp_failed",
    "http_status",
    "redirect_refused",
    "bad_url",
    "webhook_url_https",
    "email_not_set_up",
    "undecryptable",
  ];

  it("covers every code a delivery or a test may fail with", () => {
    expect(Object.keys(DELIVERY_ERRORS).sort()).toEqual([...codes].sort());
  });

  it("gives each code another text", () => {
    expect(new Set(codes.map(deliveryErrorText)).size).toBe(codes.length);
  });

  it.each(["bad_url", "webhook_url_https", "email_not_set_up"])("says %s as an answer to a request does", (code) => {
    expect(deliveryErrorText(code)).toBe(messageFor(code));
  });

  it("tells an undecryptable secret apart from a sign-in's", () => {
    expect(deliveryErrorText("undecryptable")).not.toBe(messageFor("undecryptable"));
  });

  it.each([null, "something_new", "toString"])("says the try failed for %s", (code) => {
    expect(deliveryErrorText(code)).toBe("The message could not be sent.");
  });
});

describe("reasonText", () => {
  const reasons: ConnectionReason[] = [
    "unreachable",
    "host_key_changed",
    "key_refused",
    "account_is_root",
    "account_in_docker_group",
    "account_not_in_log_groups",
    "sudo_checker_missing",
    "sudo_too_wide",
    "account_check_failed",
    "ssh_error",
  ];

  it("covers every reason", () => {
    expect(Object.keys(CONNECTION_REASONS).sort()).toEqual([...reasons].sort());
  });

  it.each(reasons)("%s has a title and advice", (reason) => {
    const { title, advice } = reasonText(reason);
    expect(title).not.toBe("");
    expect(advice).not.toBe("");
  });

  it("says the server did not answer", () => {
    expect(reasonText("unreachable").title).toBe("The server did not answer.");
  });
});

describe("monitoringText", () => {
  it("covers every monitoring reason", () => {
    expect(Object.keys(MONITORING_REASONS).sort()).toEqual(
      [
        "unreachable",
        "key_refused",
        "ssh_error",
        "no_samples",
        "not_an_ssh_server",
        "host_key_not_pinned",
        "host_key_changed",
      ].sort(),
    );
  });

  it("says no sample came for 30 seconds", () => {
    expect(monitoringText("no_samples")).toEqual({
      title: "No sample for 30 seconds.",
      advice: "The server stopped sending samples. It may be overloaded or frozen.",
    });
  });

  it("has no advice for a server that is not an SSH server", () => {
    expect(monitoringText("not_an_ssh_server")!.advice).toBeNull();
  });

  it.each([null, "something_new", "toString"])("has no text for %s", (reason) => {
    expect(monitoringText(reason)).toBeNull();
  });

  it("says the collector has not looked at the server yet", () => {
    expect(NOT_CHECKED.title).toBe("The collector has not looked at this server yet.");
  });
});
