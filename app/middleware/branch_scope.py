from app.models import User
from app.shared.exceptions import ForbiddenException


def validate_branch_access(user: User, branch_id: int, allowed_branches: list[int]) -> None:
    if branch_id not in allowed_branches:
        raise ForbiddenException(
            detail=f"User does not have access to branch {branch_id}"
        )
