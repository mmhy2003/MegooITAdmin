"""The audit action names of the server groups an Owner manages, of the servers an Admin manages in them, and of
their SSH host keys and connection tests."""

SERVER_GROUP_CREATED = "server_group.created"
SERVER_GROUP_CHANGED = "server_group.changed"
SERVER_GROUP_DELETED = "server_group.deleted"

ALL_ACTIONS = frozenset({SERVER_GROUP_CREATED, SERVER_GROUP_CHANGED, SERVER_GROUP_DELETED})

SERVER_CREATED = "server.created"
SERVER_CHANGED = "server.changed"
SERVER_MOVED = "server.moved"
SERVER_TAGS_CHANGED = "server.tags_changed"
SERVER_DELETED = "server.deleted"

SERVER_ACTIONS = frozenset({SERVER_CREATED, SERVER_CHANGED, SERVER_MOVED, SERVER_TAGS_CHANGED, SERVER_DELETED})

SERVER_HOST_KEY_FETCHED = "server.host_key_fetched"
SERVER_HOST_KEY_PINNED = "server.host_key_pinned"
SERVER_HOST_KEY_MISMATCH = "server.host_key_mismatch"
SERVER_HOST_KEY_REPLACED = "server.host_key_replaced"
SERVER_HOST_KEY_KEPT = "server.host_key_kept"
SERVER_CONNECTION_TESTED = "server.connection_tested"

CONNECTION_ACTIONS = frozenset(
    {
        SERVER_HOST_KEY_FETCHED,
        SERVER_HOST_KEY_PINNED,
        SERVER_HOST_KEY_MISMATCH,
        SERVER_HOST_KEY_REPLACED,
        SERVER_HOST_KEY_KEPT,
        SERVER_CONNECTION_TESTED,
    }
)
