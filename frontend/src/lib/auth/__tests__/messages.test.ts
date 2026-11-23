import { describe, expect, it } from "vitest";
import { messageFor } from "@/lib/auth/messages";

describe("messageFor", () => {
  it.each([
    ["invalid_credentials", "The email or the password is wrong."],
    ["unreachable", "The server is not answering. Try again in a moment."],
    ["no_such_reason", "Something went wrong. Try again."],
  ])("%s → %s", (detail, text) => {
    expect(messageFor(detail)).toBe(text);
  });
});
