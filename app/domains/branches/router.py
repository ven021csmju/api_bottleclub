from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.middleware.access import Access
from app.middleware.auth import get_access, get_current_user, require_permission
from app.shared.exceptions import ForbiddenException
from app.db.models import User

from .schemas import BranchCreate, BranchListResponse, BranchResponse, BranchUpdate
from .service import BranchService

router = APIRouter()


def _ensure_superadmin(access: Access) -> None:
    """Creating and removing branches is organization level: a Superadmin only."""
    if not access.superadmin:
        raise ForbiddenException(detail="Only a Superadmin can create or remove branches")


@router.get("/", response_model=BranchListResponse)
def list_branches(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> BranchListResponse:
    return BranchService.list_branches(db, current_user.organization_id)


@router.get("/{branch_id}", response_model=BranchResponse)
def get_branch(
    branch_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> BranchResponse:
    branch = BranchService.get_branch(db, current_user.organization_id, branch_id)
    return BranchResponse.model_validate(branch)


@router.post("/", response_model=BranchResponse, status_code=201)
def create_branch(
    data: BranchCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("branches.create", scope="org")),
    access: Access = Depends(get_access),
) -> BranchResponse:
    _ensure_superadmin(access)
    branch = BranchService.create_branch(db, current_user.organization_id, data)
    return BranchResponse.model_validate(branch)


@router.put("/{branch_id}", response_model=BranchResponse)
def update_branch(
    branch_id: int,
    data: BranchUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("branches.update", scope="any")),
    access: Access = Depends(get_access),
) -> BranchResponse:
    """A branch where the caller holds branches.update; another branch is 404.
    ``is_active`` removes or restores the branch, so it is a Superadmin's."""
    access.ensure_at("branches.update", branch_id, "Branch")
    if "is_active" in data.model_fields_set:
        _ensure_superadmin(access)
    branch = BranchService.update_branch(db, current_user.organization_id, branch_id, data)
    return BranchResponse.model_validate(branch)


@router.delete("/{branch_id}", status_code=204)
def delete_branch(
    branch_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("branches.delete", scope="org")),
    access: Access = Depends(get_access),
) -> None:
    _ensure_superadmin(access)
    BranchService.delete_branch(db, current_user.organization_id, branch_id)
