from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import SystemSetting


class SettingsRepository:
    @staticmethod
    def list_settings(
        db: Session, organization_id: int, branch_id: int | None = None
    ) -> list[SystemSetting]:
        stmt = select(SystemSetting).where(
            SystemSetting.organization_id == organization_id,
        )
        if branch_id is not None:
            stmt = stmt.where(
                (SystemSetting.branch_id == branch_id)
                | (SystemSetting.branch_id.is_(None))
            )
        else:
            stmt = stmt.where(SystemSetting.branch_id.is_(None))
        stmt = stmt.order_by(SystemSetting.key)
        return list(db.scalars(stmt).all())

    @staticmethod
    def get_branch_setting(
        db: Session, organization_id: int, key: str, branch_id: int
    ) -> SystemSetting | None:
        return db.execute(
            select(SystemSetting).where(
                SystemSetting.organization_id == organization_id,
                SystemSetting.key == key,
                SystemSetting.branch_id == branch_id,
            )
        ).scalar_one_or_none()

    @staticmethod
    def get_org_setting(
        db: Session, organization_id: int, key: str
    ) -> SystemSetting | None:
        return db.execute(
            select(SystemSetting).where(
                SystemSetting.organization_id == organization_id,
                SystemSetting.key == key,
                SystemSetting.branch_id.is_(None),
            )
        ).scalar_one_or_none()

    @staticmethod
    def get_setting_for_branch_or_none(
        db: Session, organization_id: int, key: str, branch_id: int | None
    ) -> SystemSetting | None:
        return db.execute(
            select(SystemSetting).where(
                SystemSetting.organization_id == organization_id,
                SystemSetting.key == key,
                SystemSetting.branch_id == branch_id,
            )
        ).scalar_one_or_none()

    @staticmethod
    def add_setting(db: Session, setting: SystemSetting) -> None:
        db.add(setting)