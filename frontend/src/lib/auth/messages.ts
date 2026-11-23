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
};

/** The text shown for an `ApiError` detail. */
export function messageFor(detail: string): string {
  return Object.hasOwn(MESSAGES, detail) ? MESSAGES[detail] : "Something went wrong. Try again.";
}
