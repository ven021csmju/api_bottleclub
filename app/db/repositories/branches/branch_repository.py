from sqlalchemy.orm import Session

from app.db.models import Branch


class BranchRepository:
    @staticmethod
    def list_query(db: Session, org_id: int):
        return (
            db.query(Branch)
            .filter(Branch.organization_id == org_id)
            .order_by(Branch.created_at.desc())
        )

    @staticmethod
    def get_org_branch(db: Session, org_id: int, branch_id: int) -> Branch | None:
        return (
            db.query(Branch)
            .filter(Branch.id == branch_id, Branch.organization_id == org_id)
            .first()
        )

    @staticmethod
    def find_by_code(db: Session, org_id: int, code: str) -> Branch | None:
        return (
            db.query(Branch)
            .filter(Branch.organization_id == org_id, Branch.code == code)
            .first()
        )

    @staticmethod
    def add_branch(db: Session, branch: Branch) -> None:
        db.add(branch)