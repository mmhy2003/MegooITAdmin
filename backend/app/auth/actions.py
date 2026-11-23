"""The audit action names of auth events, and the values of their result_detail."""

OWNER_CREATED = "auth.owner_created"
SETUP_FAILED = "auth.setup_failed"
SETUP_CODE_CREATED = "auth.setup_code_created"
PASSWORD_ACCEPTED = "auth.password_accepted"
SIGN_IN = "auth.sign_in"
SIGN_IN_FAILED = "auth.sign_in_failed"
SIGN_OUT = "auth.sign_out"
MFA_USED = "auth.mfa_used"
MFA_FAILED = "auth.mfa_failed"
MFA_RESET = "auth.mfa_reset"
MFA_ENROLMENT_STARTED = "auth.mfa_enrolment_started"
MFA_ENROLLED = "auth.mfa_enrolled"
RECOVERY_CODES_CREATED = "auth.recovery_codes_created"
PASSWORD_CHANGED = "auth.password_changed"
ACCOUNT_LOCKED = "auth.account_locked"
SESSION_REVOKED = "auth.session_revoked"

ALL_ACTIONS = frozenset(
    {
        OWNER_CREATED,
        SETUP_FAILED,
        SETUP_CODE_CREATED,
        PASSWORD_ACCEPTED,
        SIGN_IN,
        SIGN_IN_FAILED,
        SIGN_OUT,
        MFA_USED,
        MFA_FAILED,
        MFA_RESET,
        MFA_ENROLMENT_STARTED,
        MFA_ENROLLED,
        RECOVERY_CODES_CREATED,
        PASSWORD_CHANGED,
        ACCOUNT_LOCKED,
        SESSION_REVOKED,
    }
)

# result_detail["reason"]
UNKNOWN_ACCOUNT = "unknown_account"
WRONG_PASSWORD = "wrong_password"
LOCKED = "locked"
WRONG_CODE = "wrong_code"
EXPIRED = "expired"
UNDECRYPTABLE = "undecryptable"
NO_CODE = "no_code"
# result_detail["method"]: "totp" or "recovery_code"
