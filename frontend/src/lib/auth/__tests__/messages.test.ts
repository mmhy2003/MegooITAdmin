import { describe, expect, it } from "vitest";
import { messageFor } from "@/lib/auth/messages";

describe("messageFor", () => {
  it.each([
    ["invalid_credentials", "The email or the password is wrong."],
    ["unreachable", "The server is not answering. Try again in a moment."],
    ["forbidden", "Only the Owner can do this."],
    ["email_taken", "An account with this email exists already."],
    ["name_taken", "A server group with this name exists already."],
    ["own_account", "You cannot change your own account here."],
    ["last_owner", "At least one enabled Owner must remain."],
    ["invalid_invite", "This invite link does not work. Ask the Owner for a new one."],
    ["already_accepted", "This person has accepted their invite already."],
    ["no_change", "Nothing has changed."],
    ["no_such_reason", "Something went wrong. Try again."],
  ])("%s → %s", (detail, text) => {
    expect(messageFor(detail)).toBe(text);
  });
});
