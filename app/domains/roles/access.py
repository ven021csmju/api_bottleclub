"""Who may grant which permissions.

Authority comes from the roles a user holds in the database now, not from the
access token (it may predate a demotion) and not from ``users.is_superadmin``,
which is shown to clients but never checked. A Superadmin is a user holding
the system role named ``Superadmin`` in their own organization.
"""
from collections.abc import Iterable

from sqlalchemy.orm import Session

from app.db.models import User
from app.db.repositories.roles import RoleRepository
from app.shared.exceptions import ConflictException, ForbiddenException

SUPERADMIN_ROLE = "Superadmin"


def is_superadmin(db: Session, user: User) -> bool:
    return RoleRepository.holds_system_role(db, user.organization_id, user.id, SUPERADMIN_ROLE)


def ensure_can_grant(db: Session, actor: User, permission_ids: Iterable[int]) -> None:
    """403 unless ``actor`` holds every one of ``permission_ids`` (a Superadmin always may)."""
    wanted = set(permission_ids)
    if not wanted or is_superadmin(db, actor):
        return
    if wanted - RoleRepository.permission_ids_of_user(db, actor.organization_id, actor.id):
        raise ForbiddenException(
            detail="Cannot grant permissions you do not hold", code="PERMISSION_ESCALATION"
        )


def ensure_can_manage(db: Session, actor: User, target: User) -> None:
    """403 unless ``target`` holds no permission ``actor`` lacks; only a Superadmin
    manages a Superadmin."""
    if is_superadmin(db, actor):
        return
    org_id = actor.organization_id
    if is_superadmin(db, target) or (
        RoleRepository.permission_ids_of_user(db, org_id, target.id)
        - RoleRepository.permission_ids_of_user(db, org_id, actor.id)
    ):
        raise ForbiddenException(
            detail="Cannot change a user who has permissions you do not hold",
            code="PERMISSION_ESCALATION",
        )


def ensure_not_self(actor: User, target: User, what: str) -> None:
    if actor.id == target.id:
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
