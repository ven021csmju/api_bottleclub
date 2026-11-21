"""The signed-in customer (customer token), apart from the staff dependencies
in app/middleware/auth.py: a customer route never accepts a staff token and
a staff route never accepts a customer token."""
from fastapi import Depends, Header
from jose import JWTError
from sqlalchemy.orm import Session

from app.db.models import CustomerAccount
from app.db.session import get_db
from app.shared.exceptions import UnauthorizedException
from app.shared.security import decode_customer_token


async def get_customer_account(
    authorization: str | None = Header(None),
    db: Session = Depends(get_db),
) -> CustomerAccount:
    if not authorization or not authorization.startswith("Bearer "):
        raise UnauthorizedException(detail="Not authenticated")
    try:
        payload = decode_customer_token(authorization[7:])
    except JWTError:
        raise UnauthorizedException(detail="Invalid or expired token")
    account = db.get(CustomerAccount, int(payload["sub"]))
    if account is None or account.status != "active" or account.organization_id != payload.get("org_id"):
        raise UnauthorizedException(detail="Customer account not found")
    return account
