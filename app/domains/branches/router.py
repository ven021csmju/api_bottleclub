from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.middleware.auth import get_current_user, require_permission
from app.db.models import User

from .schemas import BranchCreate, BranchListResponse, BranchResponse, BranchUpdate
from .service import BranchService

router = APIRouter()


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
    current_user: User = Depends(require_permission("branches.create")),
) -> BranchResponse:
    branch = BranchService.create_branch(db, current_user.organization_id, data)
    return BranchResponse.model_validate(branch)


@router.put("/{branch_id}", response_model=BranchResponse)
def update_branch(
    branch_id: int,
    data: BranchUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("branches.update")),
) -> BranchResponse:
    branch = BranchService.update_branch(db, current_user.organization_id, branch_id, data)
    return BranchResponse.model_validate(branch)


@router.delete("/{branch_id}", status_code=204)
def delete_branch(
    branch_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("branches.delete")),
) -> None:
    BranchService.delete_branch(db, current_user.organization_id, branch_id)
