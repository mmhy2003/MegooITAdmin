"""The audit action names of the people an Owner manages, and the reasons a refused invite records."""

USER_INVITED = "user.invited"
USER_INVITE_RENEWED = "user.invite_renewed"
USER_INVITE_ACCEPTED = "user.invite_accepted"
USER_INVITE_REFUSED = "user.invite_refused"
USER_ROLE_CHANGED = "user.role_changed"
USER_GRANT_ADDED = "user.grant_added"
USER_GRANT_CHANGED = "user.grant_changed"
USER_GRANT_REMOVED = "user.grant_removed"
USER_DISABLED = "user.disabled"
USER_ENABLED = "user.enabled"

ALL_ACTIONS = frozenset(
    {
        USER_INVITED,
        USER_INVITE_RENEWED,
        USER_INVITE_ACCEPTED,
        USER_INVITE_REFUSED,
        USER_ROLE_CHANGED,
        USER_GRANT_ADDED,
        USER_GRANT_CHANGED,
        USER_GRANT_REMOVED,
        USER_DISABLED,
        USER_ENABLED,
    }
)

# Why an invite link was refused.
UNKNOWN = "unknown"
EXPIRED = "expired"
DISABLED = "disabled"
