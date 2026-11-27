import type { ConnectionReason, MonitoringReason } from "@/lib/servers";

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
  host_key_pinned: "A host key is pinned already. The page has been reloaded.",
  stale_host_key:
    "The server's key is no longer the one you compared. It has been fetched again: compare the new fingerprint.",
  host_key_not_changed: "This server's host key has not changed. The page has been reloaded.",
  host_key_not_pinned: "Pin the server's host key before testing the connection.",
  host_key_changed: "The server's host key has changed. Review it before connecting.",
  not_an_ssh_server: "Only Linux servers connect over SSH.",
  reason_required: "Say why you accept the new key.",
  rule_name_taken: "An alert rule with this name exists already.",
  unknown_server: "A server was removed meanwhile. The list has been reloaded.",
  bad_threshold: "The limit does not fit this measure.",
  bad_scope: "Choose all servers, one server group or one server.",
  channel_name_taken: "A channel with this name exists already.",
  too_many_channels: "There are as many channels as allowed. Delete one first.",
  webhook_url_https: "The address must start with https://.",
  bad_url: "This is not a web address.",
  bad_telegram_token: "This is not a Telegram bot token.",
  bad_chat_id: "This is not a Telegram chat ID.",
  email_not_set_up: "Set up email first.",
};

/** The text shown for an `ApiError` detail. */
export function messageFor(detail: string): string {
  return Object.hasOwn(MESSAGES, detail) ? MESSAGES[detail] : "Something went wrong. Try again.";
}

/** Why a delivery or a channel test failed. Apart from MESSAGES: `undecryptable` means another thing there. */
export const DELIVERY_ERRORS: Record<string, string> = {
  connection_failed: "The connection failed.",
  timeout: "The other side did not answer in time.",
  tls_failed: "The secure connection failed.",
  auth_failed: "The mail server refused the user name or the password.",
  recipients_refused: "The mail server refused the recipients.",
  smtp_failed: "The mail server refused the message.",
  http_status: "The address answered with an error.",
  redirect_refused: "The address answered with a redirect, which is not followed.",
  // A saved address is checked again when a message is sent, and the email settings may have changed meanwhile.
  bad_url: MESSAGES.bad_url,
  webhook_url_https: MESSAGES.webhook_url_https,
  email_not_set_up: MESSAGES.email_not_set_up,
  undecryptable: "The saved secret cannot be read any more. Enter it again.",
};

/** The text for the `error` of a delivery or a test result. */
export function deliveryErrorText(code: string | null): string {
  return code !== null && Object.hasOwn(DELIVERY_ERRORS, code) ? DELIVERY_ERRORS[code] : "The message could not be sent.";
}

export const CONNECTION_REASONS: Record<ConnectionReason, { title: string; advice: string }> = {
  unreachable: {
    title: "The server did not answer.",
    advice: "Check the address and the port, and that the server accepts SSH connections from MegooITAdmin.",
  },
  host_key_changed: {
    title: "The server presented another host key.",
    advice: "The connection stopped before signing in. Review the host key on this page.",
  },
  key_refused: {
    title: "The server refused the platform's key.",
    advice:
      "Run the setup script on the server with the platform's key (see Platform access), and check that --from holds the address the server sees MegooITAdmin connect from.",
  },
  account_is_root: {
    title: "The login account is root.",
    advice: "Use the megoo account: MegooITAdmin never signs in as root.",
  },
  account_in_docker_group: {
    title: "The login account is in the docker group.",
    advice: "Remove it from the docker group: that group is as strong as root.",
  },
  account_not_in_log_groups: {
    title: "The login account cannot read the logs.",
    advice: "Run the setup script on the server again: it adds the account to systemd-journal and adm.",
  },
  sudo_checker_missing: {
    title: "megoo-ctl is missing or out of date.",
    advice: "Run the setup script on the server again: it installs megoo-ctl and the sudo rule that allows it.",
  },
  sudo_too_wide: {
    title: "The login account may run more than megoo-ctl with sudo.",
    advice: "Remove its other sudo rights (the sudo or wheel group, other files in /etc/sudoers.d), then test again.",
  },
  account_check_failed: {
    title: "The account could not be checked.",
    advice: "The id command did not answer in time, or what sudo allows the account (sudo -l) could not be read. Try again.",
  },
  ssh_error: {
    title: "The SSH connection failed.",
    advice: "The server may offer only old algorithms, such as ssh-rsa with SHA-1, which are not supported.",
  },
};

/** The title and advice shown for a failed connection or key fetch. */
export function reasonText(reason: ConnectionReason): { title: string; advice: string } {
  return CONNECTION_REASONS[reason];
}

export type MonitoringText = { title: string; advice: string | null };

export const MONITORING_REASONS: Record<MonitoringReason, MonitoringText> = {
  unreachable: {
    title: "The server did not answer.",
    advice: "Check the address and the port, and that the server accepts SSH connections from MegooITAdmin.",
  },
  key_refused: {
    title: "The server refused the platform's key.",
    advice: "Run the setup script on the server with the platform's key (see Platform access).",
  },
  ssh_error: {
    title: "The SSH connection failed.",
    advice: "The server may offer only old algorithms, or the metrics loop could not start there.",
  },
  no_samples: {
    title: "No sample for 30 seconds.",
    advice: "The server stopped sending samples. It may be overloaded or frozen.",
  },
  not_an_ssh_server: { title: "Only Linux servers are monitored.", advice: null },
  host_key_not_pinned: {
    title: "The host key is not pinned yet.",
    advice: "Monitoring starts once the host key is pinned.",
  },
  host_key_changed: {
    title: "The host key has changed.",
    advice: "Monitoring resumes once the new key is reviewed.",
  },
};

/** The text for a server the collector has not looked at yet (`monitoring` is null). */
export const NOT_CHECKED: MonitoringText = { title: "The collector has not looked at this server yet.", advice: null };

/** The title and advice for a monitoring reason, or null for none or one this frontend does not know. */
export function monitoringText(reason: string | null): MonitoringText | null {
  return reason !== null && Object.hasOwn(MONITORING_REASONS, reason)
    ? MONITORING_REASONS[reason as MonitoringReason]
    : null;
}
