from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.middleware.auth import get_current_branch, require_permission
from app.models import User

from .schemas import (
    StockTransferCreate,
    StockTransferListResponse,
    StockTransferResponse,
    TransferReceiveItems,
    TransferShipItems,
    TransferStatusUpdate,
)
from .service import TransferService

router = APIRouter()


@router.post("/", response_model=StockTransferResponse)
def create_transfer(
    body: StockTransferCreate,
    user: User = Depends(require_permission("transfers.create")),
    branch_id: int = Depends(get_current_branch),
    db: Session = Depends(get_db),
) -> StockTransferResponse:
    transfer = TransferService.create_transfer(
        db=db,
        org_id=user.organization_id,
        source_branch_id=branch_id,
        user_id=user.id,
        data=body.model_dump(),
    )
    return StockTransferResponse.model_validate(transfer)


@router.get("/", response_model=StockTransferListResponse)
def list_transfers(
    user: User = Depends(require_permission("transfers.read")),
    db: Session = Depends(get_db),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    source_branch_id: int | None = None,
    dest_branch_id: int | None = None,
    status: str | None = None,
) -> StockTransferListResponse:
    result = TransferService.list_transfers(
        db=db,
        org_id=user.organization_id,
        source_branch_id=source_branch_id,
        dest_branch_id=dest_branch_id,
        page=page,
        per_page=per_page,
        status=status,
    )
    return StockTransferListResponse(
        transfers=[StockTransferResponse.model_validate(t) for t in result["transfers"]],
        total=result["total"],
        page=result["page"],
        per_page=result["per_page"],
    )


@router.get("/{transfer_id}", response_model=StockTransferResponse)
def get_transfer(
    transfer_id: int,
    user: User = Depends(require_permission("transfers.read")),
    db: Session = Depends(get_db),
) -> StockTransferResponse:
    transfer = TransferService.get_transfer(
        db=db,
        org_id=user.organization_id,
        transfer_id=transfer_id,
    )
    return StockTransferResponse.model_validate(transfer)


@router.put("/{transfer_id}/approve", response_model=StockTransferResponse)
def approve_transfer(
    transfer_id: int,
    user: User = Depends(require_permission("transfers.approve")),
    db: Session = Depends(get_db),
) -> StockTransferResponse:
    transfer = TransferService.approve_transfer(
        db=db,
        org_id=user.organization_id,
        transfer_id=transfer_id,
        user_id=user.id,
    )
    return StockTransferResponse.model_validate(transfer)


@router.put("/{transfer_id}/ship", response_model=StockTransferResponse)
def ship_transfer(
    transfer_id: int,
    body: TransferShipItems,
    user: User = Depends(require_permission("transfers.ship")),
    db: Session = Depends(get_db),
) -> StockTransferResponse:
    transfer = TransferService.ship_transfer(
        db=db,
        org_id=user.organization_id,
        transfer_id=transfer_id,
        user_id=user.id,
        data=body.model_dump(),
    )
    return StockTransferResponse.model_validate(transfer)


@router.put("/{transfer_id}/receive", response_model=StockTransferResponse)
def receive_transfer(
    transfer_id: int,
    body: TransferReceiveItems,
    user: User = Depends(require_permission("transfers.receive")),
    db: Session = Depends(get_db),
) -> StockTransferResponse:
    transfer = TransferService.receive_transfer(
        db=db,
        org_id=user.organization_id,
        transfer_id=transfer_id,
        user_id=user.id,
        data=body.model_dump(),
    )
    return StockTransferResponse.model_validate(transfer)


@router.put("/{transfer_id}/cancel", response_model=StockTransferResponse)
def cancel_transfer(
    transfer_id: int,
    user: User = Depends(require_permission("transfers.create")),
    db: Session = Depends(get_db),
) -> StockTransferResponse:
    transfer = TransferService.cancel_transfer(
        db=db,
        org_id=user.organization_id,
        transfer_id=transfer_id,
        user_id=user.id,
    )
    return StockTransferResponse.model_validate(transfer)
