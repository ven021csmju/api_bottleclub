"""Who may grant which permissions, and to whom.

Authority is the caller's :class:`~app.middleware.access.Access`: the roles
they hold in the database now, per branch, never the access token and never
``users.is_superadmin`` (shown to clients, never checked). A Superadmin is a
user holding the system role named ``Superadmin`` in their own organization.

Permissions are compared at the branch they would apply at: a role given at
branch X must be held by the caller at X, a role given at every branch
(branch_id NULL) at organization level.
"""
from collections.abc import Iterable

from sqlalchemy.orm import Session

from app.db.models import User
from app.db.repositories.roles import RoleRepository
from app.middleware.access import SUPERADMIN_ROLE, Access
from app.shared.exceptions import ConflictException, ForbiddenException

__all__ = [
    "SUPERADMIN_ROLE",
    "ensure_can_grant",
    "ensure_can_manage",
    "ensure_not_self",
    "ensure_superadmin_remains",
    "is_superadmin",
]


def is_superadmin(db: Session, user: User) -> bool:
    return RoleRepository.holds_system_role(db, user.organization_id, user.id, SUPERADMIN_ROLE)


def _escalation(detail: str) -> ForbiddenException:
    return ForbiddenException(detail=detail, code="PERMISSION_ESCALATION")


def ensure_can_grant(
    db: Session, access: Access, permission_ids: Iterable[int], branch_id: int | None = None
) -> None:
    """403 unless the caller holds every one of ``permission_ids`` at ``branch_id``
    (None: organization level); a Superadmin always may."""
    held = access.permissions_at(branch_id)
    wanted = set(permission_ids)
    if held is None or not wanted:
        return
    if RoleRepository.permission_codes(db, wanted) - held:
        raise _escalation("Cannot grant permissions you do not hold")


def ensure_can_manage(db: Session, access: Access, target: User) -> None:
    """403 unless, at every branch where ``target`` has a role, the caller holds
    all of that role's permissions; only a Superadmin manages a Superadmin."""
    if access.superadmin:
        return
    if is_superadmin(db, target):
        raise _escalation("Cannot change a user who has permissions you do not hold")
    for branch_id, codes in RoleRepository.assignment_codes(db, access.org_id, target.id).items():
        if codes - access.permissions_at(branch_id):
            raise _escalation("Cannot change a user who has permissions you do not hold")


def ensure_not_self(access: Access, target: User, what: str) -> None:
    if access.user_id == target.id:
        raise ForbiddenException(detail=f"Cannot change your own {what}", code="SELF_CHANGE")


def ensure_superadmin_remains(
    db: Session,
    target: User,
    *,
    deactivating: bool = False,
    removing_user_role_id: int | None = None,
) -> None:
    """409 if deactivating ``target`` or removing one of their role assignments
    leaves their organization without an active Superadmin."""
    if not is_superadmin(db, target):
        return
    left = RoleRepository.active_system_role_holders(
        db, target.organization_id, SUPERADMIN_ROLE, exclude_user_role_id=removing_user_role_id
    )
    if deactivating:
        left.discard(target.id)
    if not left:
        raise ConflictException(
            detail="The organization must keep at least one active Superadmin",
            code="LAST_SUPERADMIN",
        )
