from sqlalchemy.orm import Session

from app.db.models import SystemSetting
from app.db.repositories.settings import SettingsRepository
from app.shared.exceptions import NotFoundException


class SettingService:
    @staticmethod
    def list_settings(
        db: Session,
        organization_id: int,
        branch_id: int | None = None,
    ) -> list[SystemSetting]:
        return SettingsRepository.list_settings(db, organization_id, branch_id)

    @staticmethod
    def get_setting(
        db: Session,
        organization_id: int,
        key: str,
        branch_id: int | None = None,
    ) -> SystemSetting:
        if branch_id is not None:
            setting = SettingsRepository.get_branch_setting(
                db, organization_id, key, branch_id
            )
            if setting:
                return setting

        setting = SettingsRepository.get_org_setting(db, organization_id, key)

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
        existing = SettingsRepository.get_setting_for_branch_or_none(
            db, organization_id, key, branch_id
        )

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
        SettingsRepository.add_setting(db, setting)
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
            branch_setting = SettingsRepository.get_branch_setting(
                db, organization_id, key, branch_id
            )
            if branch_setting:
                return branch_setting

        return SettingService.get_setting(db, organization_id, key)