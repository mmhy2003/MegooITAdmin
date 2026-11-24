const MESSAGES: Record<string, string> = {
  invalid_credentials: "The email or the password is wrong.",
  wrong_code: "That code is not right. Check the clock of your phone and try again.",
  locked: "This account is locked for 15 minutes after too many failed attempts.",
  undecryptable: "This account's authenticator cannot be checked any more. Ask the host's administrator to run make reset-mfa.",
  wrong_setup_code: "The setup code is not right.",
  no_setup_code: "There is no valid setup code. Run make setup-code on the host and enter the new code.",
  wrong_password: "The current password is wrong.",
  not_signed_in: "Your sign-in took too long. Start again.",
  unreachable: "The server is not answering. Try again in a moment.",
  invalid: "Check the fields and try again.",
  forbidden: "You do not have the rights to do this.",
  email_taken: "An account with this email exists already.",
  name_taken: "A server group with this name exists already.",
  own_account: "You cannot change your own account here.",
  last_owner: "At least one enabled Owner must remain.",
  invalid_invite: "This invite link does not work. Ask the Owner for a new one.",
  already_accepted: "This person has accepted their invite already.",
  no_change: "Nothing has changed.",
  unknown_group: "A server group was deleted meanwhile. The list has been reloaded.",
  server_name_taken: "A server with this name exists already.",
  group_has_servers: "This group still holds servers. Move or remove them first.",
  not_found: "It does not exist, or you cannot see it.",
};

/** The text shown for an `ApiError` detail. */
export function messageFor(detail: string): string {
  return Object.hasOwn(MESSAGES, detail) ? MESSAGES[detail] : "Something went wrong. Try again.";
}
