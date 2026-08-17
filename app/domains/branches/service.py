from sqlalchemy.orm import Session

from app.models import Branch
from app.shared.exceptions import ConflictException, NotFoundException
from app.shared.pagination import paginate

from .schemas import BranchCreate, BranchListResponse, BranchResponse, BranchUpdate


class BranchService:
    @staticmethod
    def list_branches(db: Session, org_id: int) -> BranchListResponse:
        query = (
            db.query(Branch)
            .filter(Branch.organization_id == org_id)
            .order_by(Branch.created_at.desc())
        )

        items, total, _, _ = paginate(db, query, 1, 1000)
        return BranchListResponse(
            branches=[BranchResponse.model_validate(b) for b in items],
            total=total,
        )

    @staticmethod
    def get_branch(db: Session, org_id: int, branch_id: int) -> Branch:
        branch = (
            db.query(Branch)
            .filter(Branch.id == branch_id, Branch.organization_id == org_id)
            .first()
        )
        if not branch:
            raise NotFoundException(detail="Branch not found")
        return branch

    @staticmethod
    def create_branch(db: Session, org_id: int, data: BranchCreate) -> Branch:
        existing = (
            db.query(Branch)
            .filter(Branch.organization_id == org_id, Branch.code == data.code)
            .first()
        )
        if existing:
            raise ConflictException(detail="Branch with this code already exists")

        branch = Branch(
            organization_id=org_id,
            name=data.name,
            code=data.code,
            phone=data.phone,
            address=data.address,
        )
        db.add(branch)
        db.commit()
        db.refresh(branch)
        return branch

    @staticmethod
    def update_branch(db: Session, org_id: int, branch_id: int, data: BranchUpdate) -> Branch:
        branch = BranchService.get_branch(db, org_id, branch_id)

        update_data = data.model_dump(exclude_unset=True)
        for field, value in update_data.items():
            setattr(branch, field, value)

        db.commit()
        db.refresh(branch)
        return branch

    @staticmethod
    def delete_branch(db: Session, org_id: int, branch_id: int) -> None:
        branch = BranchService.get_branch(db, org_id, branch_id)
        branch.is_active = False
        db.commit()
