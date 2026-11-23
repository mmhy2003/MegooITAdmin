"""The seven grant switches of a group role, and the platform and group roles."""

from enum import StrEnum


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


# The fields of a group role that audit events compare: the role and the seven switches.
GRANT_FIELDS = ("role", *(p.value for p in Permission))
