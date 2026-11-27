"""The audit action names of the log file allowlist an Admin manages, and of the log streams people open."""

LOG_ALLOWLIST_PATTERN_ADDED = "log_allowlist.pattern_added"
LOG_ALLOWLIST_PATTERN_REMOVED = "log_allowlist.pattern_removed"

ALLOWLIST_ACTIONS = frozenset({LOG_ALLOWLIST_PATTERN_ADDED, LOG_ALLOWLIST_PATTERN_REMOVED})

LOGS_STREAM_OPENED = "logs.stream_opened"
LOGS_STREAM_CLOSED = "logs.stream_closed"

STREAM_ACTIONS = frozenset({LOGS_STREAM_OPENED, LOGS_STREAM_CLOSED})
