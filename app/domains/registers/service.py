"""Cash registers of a branch (Phase 38a): a shift opens on one of them."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Branch, Register, Shift
from app.db.repositories.branches import BranchRepository
from app.shared.exceptions import ConflictException, NotFoundException


def _org_register(db: Session, org_id: int, register_id: int) -> Register:
    register = db.scalar(
        select(Register)
        .join(Branch, Branch.id == Register.branch_id)
        .where(Register.id == register_id, Branch.organization_id == org_id)
    )
    if register is None:
        raise NotFoundException(detail="Register not found")
    return register


def _name_taken(db: Session, branch_id: int, name: str, other_than: int | None = None) -> bool:
    stmt = select(Register.id).where(Register.branch_id == branch_id, Register.name == name)
    if other_than is not None:
        stmt = stmt.where(Register.id != other_than)
    return db.scalar(stmt) is not None


class RegisterService:
    @staticmethod
    def get_register(db: Session, org_id: int, register_id: int) -> Register:
        return _org_register(db, org_id, register_id)

    @staticmethod
    def list_registers(db: Session, branch_id: int, include_inactive: bool = False) -> list[Register]:
        stmt = select(Register).where(Register.branch_id == branch_id)
        if not include_inactive:
            stmt = stmt.where(Register.is_active.is_(True))
        return list(db.scalars(stmt.order_by(Register.name)))

    @staticmethod
    def create_register(db: Session, org_id: int, branch_id: int, name: str) -> Register:
        if not BranchRepository.get_org_branch(db, org_id, branch_id):
            raise NotFoundException(detail="Branch not found")
        if _name_taken(db, branch_id, name):
            raise ConflictException(detail=f"The branch already has a register named '{name}'",
                                    code="REGISTER_NAME_TAKEN")
        register = Register(branch_id=branch_id, name=name)
        db.add(register)
        db.commit()
        db.refresh(register)
        return register

    @staticmethod
    def update_register(db: Session, org_id: int, register_id: int, data: dict) -> Register:
        register = _org_register(db, org_id, register_id)
        name = data.get("name")
        if name is not None and name != register.name:
            if _name_taken(db, register.branch_id, name, other_than=register.id):
                raise ConflictException(detail=f"The branch already has a register named '{name}'",
                                        code="REGISTER_NAME_TAKEN")
            register.name = name
        if data.get("is_active") is False and register.is_active:
            open_shift = db.scalar(
                select(Shift.id).where(Shift.register_id == register.id, Shift.status == "open")
            )
            if open_shift is not None:
                raise ConflictException(detail="Close the open shift on this register first",
                                        code="REGISTER_HAS_OPEN_SHIFT")
        if data.get("is_active") is not None:
            register.is_active = data["is_active"]
        db.commit()
        db.refresh(register)
        return register
