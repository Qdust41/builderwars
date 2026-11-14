from __future__ import annotations

import pytest

from domain.common import ConflictError, NotFoundError, PermissionDeniedError
from domain.projects import ProjectRole
from domain.users import User


@pytest.fixture
def pid(world) -> str:
    for name in ("owner", "adam", "mia", "vic", "bob"):
        world.users.add(User(user_id=name, email=f"{name}@example.com"))
    pid = world.projects.create_project(user_id="owner", name="Rover").id
    add = world.projects.add_member
    add(user_id="owner", project_id=pid, email="adam@example.com", role=ProjectRole.ADMIN)
    add(user_id="owner", project_id=pid, email="mia@example.com", role=ProjectRole.MEMBER)
    add(user_id="owner", project_id=pid, email="vic@example.com", role=ProjectRole.VIEWER)
    return pid


def test_members_are_listed_owner_first_with_emails(world, pid: str) -> None:
    members = world.projects.list_members(user_id="vic", project_id=pid)
    assert [(m.membership.user_id, m.membership.role, m.email) for m in members] == [
        ("owner", ProjectRole.OWNER, "owner@example.com"),
        ("adam", ProjectRole.ADMIN, "adam@example.com"),
        ("mia", ProjectRole.MEMBER, "mia@example.com"),
        ("vic", ProjectRole.VIEWER, "vic@example.com"),
    ]


def test_added_member_sees_the_project(world, pid: str) -> None:
    world.projects.add_member(
        user_id="adam", project_id=pid, email=" BOB@example.com", role=ProjectRole.VIEWER
    )
    assert [p.id for p in world.projects.list_projects(user_id="bob")] == [pid]


def test_non_members_get_not_found(world, pid: str) -> None:
    with pytest.raises(NotFoundError):
        world.projects.list_members(user_id="bob", project_id=pid)
    with pytest.raises(NotFoundError):
        world.projects.add_member(
            user_id="bob", project_id=pid, email="bob@example.com", role=ProjectRole.VIEWER
        )


@pytest.mark.parametrize("actor", ["mia", "vic"])
def test_members_and_viewers_cannot_add_members(world, pid: str, actor: str) -> None:
    with pytest.raises(PermissionDeniedError):
        world.projects.add_member(
            user_id=actor, project_id=pid, email="bob@example.com", role=ProjectRole.VIEWER
        )


def test_only_the_owner_grants_admin_and_nobody_grants_owner(world, pid: str) -> None:
    with pytest.raises(PermissionDeniedError, match="only the project owner"):
        world.projects.add_member(
            user_id="adam", project_id=pid, email="bob@example.com", role=ProjectRole.ADMIN
        )
    with pytest.raises(PermissionDeniedError, match="cannot be granted"):
        world.projects.add_member(
            user_id="owner", project_id=pid, email="bob@example.com", role=ProjectRole.OWNER
        )


def test_unknown_email_and_existing_member(world, pid: str) -> None:
    with pytest.raises(NotFoundError, match="user"):
        world.projects.add_member(
            user_id="owner", project_id=pid, email="nobody@example.com", role=ProjectRole.MEMBER
        )
    with pytest.raises(ConflictError):
        world.projects.add_member(
            user_id="owner", project_id=pid, email="mia@example.com", role=ProjectRole.VIEWER
        )


def test_admin_removes_members_but_not_admins_or_owner(world, pid: str) -> None:
    world.projects.remove_member(user_id="adam", project_id=pid, member_user_id="mia")
    with pytest.raises(NotFoundError):
        world.projects.get_project(user_id="mia", project_id=pid)
    with pytest.raises(PermissionDeniedError):
        world.projects.remove_member(user_id="adam", project_id=pid, member_user_id="owner")
    world.users.add(User(user_id="ada2", email="ada2@example.com"))
    world.projects.add_member(
        user_id="owner", project_id=pid, email="ada2@example.com", role=ProjectRole.ADMIN
    )
    with pytest.raises(PermissionDeniedError, match="only the project owner"):
        world.projects.remove_member(user_id="adam", project_id=pid, member_user_id="ada2")
    world.projects.remove_member(user_id="owner", project_id=pid, member_user_id="ada2")


def test_removing_a_non_member_is_not_found(world, pid: str) -> None:
    with pytest.raises(NotFoundError, match="member"):
        world.projects.remove_member(user_id="owner", project_id=pid, member_user_id="bob")


def test_members_can_leave_but_the_owner_cannot(world, pid: str) -> None:
    world.projects.remove_member(user_id="vic", project_id=pid, member_user_id="vic")
    assert world.projects.list_projects(user_id="vic") == []
    with pytest.raises(PermissionDeniedError):
        world.projects.remove_member(user_id="owner", project_id=pid, member_user_id="owner")


def test_viewer_cannot_remove_others(world, pid: str) -> None:
    with pytest.raises(PermissionDeniedError):
        world.projects.remove_member(user_id="vic", project_id=pid, member_user_id="mia")
