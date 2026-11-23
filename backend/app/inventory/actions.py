"""The audit action names of the server groups an Owner manages."""

SERVER_GROUP_CREATED = "server_group.created"
SERVER_GROUP_CHANGED = "server_group.changed"
SERVER_GROUP_DELETED = "server_group.deleted"

ALL_ACTIONS = frozenset({SERVER_GROUP_CREATED, SERVER_GROUP_CHANGED, SERVER_GROUP_DELETED})
