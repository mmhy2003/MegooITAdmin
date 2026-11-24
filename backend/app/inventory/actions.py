"""The audit action names of the server groups an Owner manages, and of the servers an Admin manages in them."""

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
