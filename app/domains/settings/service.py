from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import SystemSetting
from app.shared.exceptions import NotFoundException


class SettingService:
    @staticmethod
    def list_settings(
        db: Session,
        organization_id: int,
        branch_id: int | None = None,
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
    def get_setting(
        db: Session,
        organization_id: int,
        key: str,
        branch_id: int | None = None,
    ) -> SystemSetting:
        if branch_id is not None:
            setting = db.execute(
                select(SystemSetting).where(
                    SystemSetting.organization_id == organization_id,
                    SystemSetting.key == key,
                    SystemSetting.branch_id == branch_id,
                )
            ).scalar_one_or_none()
            if setting:
                return setting

        setting = db.execute(
            select(SystemSetting).where(
                SystemSetting.organization_id == organization_id,
                SystemSetting.key == key,
                SystemSetting.branch_id.is_(None),
            )
        ).scalar_one_or_none()

        if setting is None:
            raise NotFoundException(detail=f"Setting '{key}' not found")
        return setting

    @staticmethod
    def update_setting(
        db: Session,
        organization_id: int,
        key: str,
        value: str,
        value_type: str | None = None,
        branch_id: int | None = None,
    ) -> SystemSetting:
        existing = db.execute(
            select(SystemSetting).where(
                SystemSetting.organization_id == organization_id,
                SystemSetting.key == key,
                SystemSetting.branch_id == branch_id,
            )
        ).scalar_one_or_none()

        if existing:
            existing.value = value
            if value_type:
                existing.value_type = value_type
            db.commit()
            db.refresh(existing)
            return existing

        setting = SystemSetting(
            organization_id=organization_id,
            branch_id=branch_id,
            key=key,
            value=value,
            value_type=value_type or "string",
        )
        db.add(setting)
        db.commit()
        db.refresh(setting)
        return setting

    @staticmethod
    def get_effective_setting(
        db: Session,
        organization_id: int,
        key: str,
        branch_id: int | None = None,
    ) -> SystemSetting:
        if branch_id is not None:
            branch_setting = db.execute(
                select(SystemSetting).where(
                    SystemSetting.organization_id == organization_id,
                    SystemSetting.key == key,
                    SystemSetting.branch_id == branch_id,
                )
            ).scalar_one_or_none()
            if branch_setting:
                return branch_setting

        return SettingService.get_setting(db, organization_id, key)
