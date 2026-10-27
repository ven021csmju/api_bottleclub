from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.db.models import User
from app.db.session import get_db
from app.domains.registers.schemas import (
    RegisterCreate,
    RegisterListResponse,
    RegisterResponse,
    RegisterUpdate,
)
from app.domains.registers.service import RegisterService
from app.middleware.access import Access
from app.middleware.auth import get_access, require_permission

router = APIRouter()

#: Who may see the registers of a branch: anyone who can work shifts there.
READ = "shifts.read"
#: Who may add, rename or close them: a Branch Admin of that branch, a Superadmin.
WRITE = "branches.update"


@router.get("/", response_model=RegisterListResponse)
def list_registers(
    branch_id: Optional[int] = Query(None),
    include_inactive: bool = Query(False),
    db: Session = Depends(get_db),
    user: User = Depends(require_permission(READ, scope="any")),
    access: Access = Depends(get_access),
) -> RegisterListResponse:
    branch_id = access.target_branch(READ, branch_id)
    registers = RegisterService.list_registers(db, branch_id, include_inactive)
    return RegisterListResponse(registers=registers, total=len(registers))


@router.post("/", response_model=RegisterResponse, status_code=201)
def create_register(
    body: RegisterCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission(WRITE, scope="any")),
    access: Access = Depends(get_access),
) -> RegisterResponse:
    access.ensure_at(WRITE, body.branch_id, "Branch")
    return RegisterService.create_register(db, user.organization_id, body.branch_id, body.name)


@router.put("/{register_id}", response_model=RegisterResponse)
def update_register(
    register_id: int,
    body: RegisterUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission(WRITE, scope="any")),
    access: Access = Depends(get_access),
) -> RegisterResponse:
    register = RegisterService.get_register(db, user.organization_id, register_id)
    access.ensure_at(WRITE, register.branch_id, "Register")
    return RegisterService.update_register(db, user.organization_id, register_id, body.model_dump(exclude_unset=True))
