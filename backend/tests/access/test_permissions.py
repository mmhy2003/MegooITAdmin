import dataclasses
from types import MappingProxyType
from uuid import uuid4

import pytest

from app.access.permissions import (
    ALL_PERMISSIONS,
    ALLOWED,
    USUAL,
    Access,
    GroupGrant,
    GroupRole,
    Permission,
    PlatformRole,
)

STAGING = uuid4()
PRODUCTION = uuid4()


def access(platform_role=None, groups=None):
    return Access(user_id=uuid4(), platform_role=platform_role, groups=MappingProxyType(groups or {}))


def test_an_owner_is_allowed_everything_everywhere():
    owner = access(PlatformRole.OWNER)

    assert owner.is_owner is True
    for group_id in (STAGING, PRODUCTION):
        assert owner.sees(group_id) is True
        for permission in Permission:
            assert owner.allows(permission, group_id) is True


def test_an_auditor_sees_every_group_and_is_allowed_none_of_the_seven():
    auditor = access(PlatformRole.AUDITOR)

    assert auditor.is_owner is False
    for group_id in (STAGING, PRODUCTION):
        assert auditor.sees(group_id) is True
        for permission in Permission:
            assert auditor.allows(permission, group_id) is False


def test_a_staging_only_admin_sees_staging_only_and_may_connect_there_only():
    admin = access(groups={STAGING: GroupGrant(GroupRole.ADMIN, ALL_PERMISSIONS)})

    assert admin.is_owner is False
    assert admin.sees(STAGING) is True
    assert admin.sees(PRODUCTION) is False
    assert admin.allows(Permission.CONNECT_SSH, STAGING) is True
    assert admin.allows(Permission.CONNECT_RDP, STAGING) is True
    for permission in Permission:
        assert admin.allows(permission, PRODUCTION) is False


def test_a_switch_that_is_off_is_refused_although_the_role_is_admin():
    admin = access(
        groups={STAGING: GroupGrant(GroupRole.ADMIN, ALL_PERMISSIONS - {Permission.CONNECT_SSH})},
    )

    assert admin.allows(Permission.CONNECT_SSH, STAGING) is False
    assert admin.allows(Permission.CONNECT_RDP, STAGING) is True


def test_a_person_without_roles_sees_no_group():
    nobody = access()

    assert nobody.sees(STAGING) is False
    assert nobody.visible_group_ids() == frozenset()
    for permission in Permission:
        assert nobody.allows(permission, STAGING) is False


def test_visible_group_ids_is_none_for_owner_and_auditor_and_the_groups_otherwise():
    assert access(PlatformRole.OWNER).visible_group_ids() is None
    assert access(PlatformRole.AUDITOR).visible_group_ids() is None

    person = access(
        groups={
            STAGING: GroupGrant(GroupRole.ADMIN, ALL_PERMISSIONS),
            PRODUCTION: GroupGrant(GroupRole.OPERATOR, frozenset()),
        },
    )
    assert person.visible_group_ids() == frozenset({STAGING, PRODUCTION})


def test_the_usual_switches_of_each_role():
    assert USUAL[GroupRole.ADMIN] == frozenset(Permission)
    assert USUAL[GroupRole.OPERATOR] == frozenset(
        {
            Permission.CONNECT_SSH,
            Permission.CONNECT_RDP,
            Permission.VIEW_LOGS,
            Permission.VIEW_PROCESSES,
            Permission.RUN_PLAYBOOKS,
        }
    )
    for role in GroupRole:
        assert USUAL[role] <= ALLOWED[role]


def test_an_operator_may_never_hold_manage_playbooks():
    assert Permission.MANAGE_PLAYBOOKS not in ALLOWED[GroupRole.OPERATOR]
    assert ALLOWED[GroupRole.OPERATOR] == frozenset(Permission) - {Permission.MANAGE_PLAYBOOKS}
    assert ALLOWED[GroupRole.ADMIN] == frozenset(Permission)


def test_access_is_immutable():
    admin = access(groups={STAGING: GroupGrant(GroupRole.ADMIN, ALL_PERMISSIONS)})

    with pytest.raises(dataclasses.FrozenInstanceError):
        admin.platform_role = PlatformRole.OWNER
    with pytest.raises(dataclasses.FrozenInstanceError):
        admin.groups[STAGING].role = GroupRole.OPERATOR
    with pytest.raises(TypeError):
        admin.groups[PRODUCTION] = GroupGrant(GroupRole.ADMIN, ALL_PERMISSIONS)


def test_manages_is_true_for_an_owner_everywhere_and_for_an_admin_in_their_group_only():
    owner = access(PlatformRole.OWNER)
    admin = access(groups={STAGING: GroupGrant(GroupRole.ADMIN, ALL_PERMISSIONS)})

    for group_id in (STAGING, PRODUCTION):
        assert owner.manages(group_id) is True
    assert admin.manages(STAGING) is True
    assert admin.manages(PRODUCTION) is False


def test_an_operator_and_an_auditor_manage_nothing():
    operator = access(groups={STAGING: GroupGrant(GroupRole.OPERATOR, USUAL[GroupRole.OPERATOR])})
    auditor = access(PlatformRole.AUDITOR)

    for group_id in (STAGING, PRODUCTION):
        assert operator.manages(group_id) is False
        assert auditor.manages(group_id) is False
