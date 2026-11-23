"""The seven grant switches of a group role, the platform and group roles, and who may use them where."""

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID


class Permission(StrEnum):
    CONNECT_SSH = "connect_ssh"
    CONNECT_RDP = "connect_rdp"
    VIEW_LOGS = "view_logs"
    VIEW_PROCESSES = "view_processes"
    MANAGE_PROCESSES = "manage_processes"
    RUN_PLAYBOOKS = "run_playbooks"
    MANAGE_PLAYBOOKS = "manage_playbooks"


class PlatformRole(StrEnum):
    OWNER = "owner"
    AUDITOR = "auditor"


class GroupRole(StrEnum):
    ADMIN = "admin"
    OPERATOR = "operator"


ALL_PERMISSIONS = frozenset(Permission)

# The switches a role ticks when it is chosen.
USUAL: dict[GroupRole, frozenset[Permission]] = {
    GroupRole.ADMIN: ALL_PERMISSIONS,
    GroupRole.OPERATOR: frozenset(
        {
            Permission.CONNECT_SSH,
            Permission.CONNECT_RDP,
            Permission.VIEW_LOGS,
            Permission.VIEW_PROCESSES,
            Permission.RUN_PLAYBOOKS,
        }
    ),
}

# The switches a role may hold: an Operator never manages playbooks (PRD §14.1).
ALLOWED: dict[GroupRole, frozenset[Permission]] = {
    GroupRole.ADMIN: ALL_PERMISSIONS,
    GroupRole.OPERATOR: ALL_PERMISSIONS - {Permission.MANAGE_PLAYBOOKS},
}

# The fields of a group role that audit events compare: the role and the seven switches.
GRANT_FIELDS = ("role", *(p.value for p in Permission))


@dataclass(frozen=True)
class GroupGrant:
    role: GroupRole
    permissions: frozenset[Permission]


@dataclass(frozen=True)
class Access:
    """A person's platform role and group roles; `groups` is built as a MappingProxyType."""

    user_id: UUID
    platform_role: PlatformRole | None
    groups: Mapping[UUID, GroupGrant]

    @property
    def is_owner(self) -> bool:
        return self.platform_role == PlatformRole.OWNER

    def sees(self, group_id: UUID) -> bool:
        return self.platform_role is not None or group_id in self.groups

    def allows(self, permission: Permission, group_id: UUID) -> bool:
        if self.is_owner:
            return True
        if self.platform_role == PlatformRole.AUDITOR:
            return False
        grant = self.groups.get(group_id)
        return grant is not None and permission in grant.permissions

    def visible_group_ids(self) -> frozenset[UUID] | None:
        """The groups this person sees, or None when they see every group."""
        if self.platform_role is not None:
            return None
        return frozenset(self.groups)
