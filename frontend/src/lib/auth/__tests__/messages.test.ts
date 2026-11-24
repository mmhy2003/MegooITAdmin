import { describe, expect, it } from "vitest";
import { CONNECTION_REASONS, messageFor, reasonText } from "@/lib/auth/messages";
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
