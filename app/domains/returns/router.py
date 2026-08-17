from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.middleware.auth import get_current_branch, require_permission
from app.models import User

from .schemas import (
    ReturnCreate,
    ReturnListResponse,
    ReturnResponse,
    ReturnStatusUpdate,
)
from .service import ReturnService

router = APIRouter()


@router.post("/", response_model=ReturnResponse)
def create_return(
    body: ReturnCreate,
    user: User = Depends(require_permission("returns.create")),
    branch_id: int = Depends(get_current_branch),
    db: Session = Depends(get_db),
) -> ReturnResponse:
    ret = ReturnService.create_return(
        db=db,
        org_id=user.organization_id,
        branch_id=branch_id,
        user_id=user.id,
        data=body.model_dump(),
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
    user: User = Depends(require_permission("returns.read")),
    db: Session = Depends(get_db),
) -> ReturnResponse:
    ret = ReturnService.get_return(db=db, return_id=return_id)
    return ReturnResponse.model_validate(ret)


@router.put("/{return_id}/process", response_model=ReturnResponse)
def process_return(
    return_id: int,
    user: User = Depends(require_permission("returns.process")),
    db: Session = Depends(get_db),
) -> ReturnResponse:
    ret = ReturnService.process_return(
        db=db,
        return_id=return_id,
        user_id=user.id,
    )
    return ReturnResponse.model_validate(ret)
