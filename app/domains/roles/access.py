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
from app.shared.exceptions import ForbiddenException

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
