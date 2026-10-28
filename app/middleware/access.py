"""What the caller may do, and at which branches (Phase 35c).

Read from the database once per request; the access token's ``permissions``
and ``branches`` claims are shown to clients but never trusted, so a role
change takes effect on the next request.

- A role assigned with ``branch_id`` NULL applies at every branch of the
  organization and to organization-level routes.
- A role assigned at branch X applies at branch X only: someone who is Manager
  at A and Cashier at B has only the Cashier permissions at B.
- A holder of the ``Superadmin`` system role may do everything, everywhere.

Routes check a permission at one of three places (``require_permission``):

``branch`` (default)
    the branch sent in ``X-Branch-Id``; without the header, organization level.
``org``
    organization level only, whatever the header says (catalog, promotions,
    coupons, branches and role management, organization settings, audit).
``any``
    held at any branch at all; the route then checks the branch of the record
    it touches with :meth:`Access.branches` and answers 404 outside it.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.db.models import Branch, Order, Permission, Role, RolePermission, UserRole
from app.shared.exceptions import BranchRequiredException, ForbiddenException, NotFoundException
from app.shared.permissions import normalize_permission

SUPERADMIN_ROLE = "Superadmin"

#: ``Access.branches()`` result meaning "every branch of the organization".
ALL_BRANCHES = None


@dataclass(frozen=True)
class Access:
    user_id: int
    org_id: int
    superadmin: bool
    org_wide: frozenset[str]
    by_branch: dict[int, frozenset[str]] = field(default_factory=dict)
    #: The branch of ``X-Branch-Id``, checked; None without the header.
    branch_id: int | None = None

    @staticmethod
    def _code(code: str) -> str:
        return normalize_permission(code)

    def can(self, code: str, branch_id: int | None) -> bool:
        """``code`` at ``branch_id`` (None: organization level)."""
        code = self._code(code)
        if self.superadmin or code in self.org_wide:
            return True
        return branch_id is not None and code in self.by_branch.get(branch_id, ())

    def can_anywhere(self, code: str) -> bool:
        code = self._code(code)
        return self.can(code, None) or any(code in codes for codes in self.by_branch.values())

    def branches(self, code: str) -> frozenset[int] | None:
        """Branches where ``code`` is held; ``ALL_BRANCHES`` (None) for every branch."""
        code = self._code(code)
        if self.can(code, None):
            return ALL_BRANCHES
        return frozenset(b for b, codes in self.by_branch.items() if code in codes)

    def visible_branches(self) -> frozenset[int] | None:
        """Branches the caller works at: every one (``ALL_BRANCHES``) for a
        Superadmin or a role held organization-wide, else those of their roles."""
        if self.superadmin or self.org_wide:
            return ALL_BRANCHES
        return frozenset(self.by_branch)

    def can_at(self, code: str, branch_id: int) -> bool:
        allowed = self.branches(code)
        return allowed is ALL_BRANCHES or branch_id in allowed

    def ensure_at(self, code: str, branch_id: int | None, what: str = "Resource") -> None:
        """404 unless ``code`` is held at ``branch_id``: a record of another branch
        is reported as missing, not as forbidden."""
        if branch_id is None or not self.can_at(code, branch_id):
            raise NotFoundException(detail=f"{what} not found")

    def permissions_at(self, branch_id: int | None) -> frozenset[str] | None:
        """Codes held at ``branch_id`` (None: organization level); None for a Superadmin."""
        if self.superadmin:
            return None
        if branch_id is None:
            return self.org_wide
        return self.org_wide | self.by_branch.get(branch_id, frozenset())

    def target_branch(self, code: str, branch_id: int | None) -> int:
        """The branch a list or report is about: ``branch_id`` if given, else the
        active branch; 404 outside the branches where ``code`` is held."""
        if branch_id is None:
            branch_id = self.branch_id
            if branch_id is None:
                raise BranchRequiredException()
        self.ensure_at(code, branch_id, "Branch")
        return branch_id


def order_branch(db: Session, org_id: int, order_id: int) -> int | None:
    """Branch of an order of ``org_id``; None if there is no such order."""
    return db.scalar(select(Order.branch_id).where(Order.id == order_id, Order.organization_id == org_id))


def load_access(db: Session, user_id: int, org_id: int, branch_header: int | None) -> Access:
    rows = db.execute(
        select(UserRole.branch_id, Role.name, Role.is_system, Permission.code)
        .join(Role, Role.id == UserRole.role_id)
        .outerjoin(Branch, Branch.id == UserRole.branch_id)
        .outerjoin(RolePermission, RolePermission.role_id == Role.id)
        .outerjoin(Permission, Permission.id == RolePermission.permission_id)
        .where(
            UserRole.user_id == user_id,
            Role.organization_id == org_id,
            # Ignore assignments to branches of another organization (pre-35b data).
            or_(UserRole.branch_id.is_(None), Branch.organization_id == org_id),
        )
    ).all()

    superadmin = False
    org_wide: set[str] = set()
    by_branch: dict[int, set[str]] = {}
    for branch_id, role_name, is_system, code in rows:
        if is_system and role_name == SUPERADMIN_ROLE:
            superadmin = True
        codes = org_wide if branch_id is None else by_branch.setdefault(branch_id, set())
        if code is not None:
            codes.add(code)

    access = Access(
        user_id=user_id,
        org_id=org_id,
        superadmin=superadmin,
        org_wide=frozenset(org_wide),
        by_branch={b: frozenset(c) for b, c in by_branch.items()},
    )
    if branch_header is None:
        return access

    in_org = db.scalar(
        select(Branch.id).where(Branch.id == branch_header, Branch.organization_id == org_id)
    )
    # Same answer for a branch of another organization, a missing one and one
    # where the caller has no role.
    if in_org is None or not (superadmin or org_wide or branch_header in by_branch):
        raise ForbiddenException(detail=f"User does not have access to branch {branch_header}")
    return Access(**{**access.__dict__, "branch_id": branch_header})
