from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.middleware.access import Access, order_branch
from app.middleware.auth import get_access, get_current_branch, require_permission
from app.shared.exceptions import NotFoundException
from app.db.models import User

from .schemas import (
    ReturnCreate,
    ReturnListResponse,
    ReturnResponse,
    ReturnStatusUpdate,
)
from .service import ReturnService

router = APIRouter()


def _scoped_return(db: Session, access: Access, return_id: int, code: str) -> None:
    """404 unless the return is of the caller's organization and ``code`` is held at its branch."""
    ret = ReturnService.get_return(db=db, return_id=return_id)
    if ret.organization_id != access.org_id:
        raise NotFoundException(detail="Return not found")
    access.ensure_at(code, ret.branch_id, "Return")


@router.post("/", response_model=ReturnResponse)
def create_return(
    request: Request,
    body: ReturnCreate,
    user: User = Depends(require_permission("returns.create")),
    branch_id: int = Depends(get_current_branch),
    access: Access = Depends(get_access),
    db: Session = Depends(get_db),
) -> ReturnResponse:
    # The order must be of a branch where the caller may take returns too.
    access.ensure_at("returns.create", order_branch(db, access.org_id, body.order_id), "Order")
    ret = ReturnService.create_return(
        db=db,
        org_id=user.organization_id,
        branch_id=branch_id,
        user_id=user.id,
        data=body.model_dump(),
        request_id=getattr(request.state, "request_id", ""),
    )
    return ReturnResponse.model_validate(ret)


@router.get("/", response_model=ReturnListResponse)
def list_returns(
    user: User = Depends(require_permission("returns.read")),
    branch_id: int = Depends(get_current_branch),
    db: Session = Depends(get_db),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
) -> ReturnListResponse:
    result = ReturnService.list_returns(
        db=db,
        org_id=user.organization_id,
        branch_id=branch_id,
        page=page,
        per_page=per_page,
    )
    return ReturnListResponse(
        returns=[ReturnResponse.model_validate(r) for r in result["returns"]],
        total=result["total"],
        page=result["page"],
        per_page=result["per_page"],
    )


@router.get("/{return_id}", response_model=ReturnResponse)
def get_return(
    return_id: int,
    user: User = Depends(require_permission("returns.read", scope="any")),
    access: Access = Depends(get_access),
    db: Session = Depends(get_db),
) -> ReturnResponse:
    _scoped_return(db, access, return_id, "returns.read")
    ret = ReturnService.get_return(db=db, return_id=return_id)
    return ReturnResponse.model_validate(ret)


@router.put("/{return_id}/process", response_model=ReturnResponse)
def process_return(
    return_id: int,
    user: User = Depends(require_permission("returns.process", scope="any")),
    access: Access = Depends(get_access),
    db: Session = Depends(get_db),
) -> ReturnResponse:
    _scoped_return(db, access, return_id, "returns.process")
    ret = ReturnService.process_return(
        db=db,
        return_id=return_id,
        user_id=user.id,
    )
    return ReturnResponse.model_validate(ret)
