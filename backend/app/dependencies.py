from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.constants import UserRole
from app.core.exceptions import AuthError, ForbiddenError
from app.core.security import decode_token
from app.db.collections import get_users_col

bearer = HTTPBearer(auto_error=False)


async def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
) -> dict:
    # Short-circuit if already resolved for this request (multiple deps can call this)
    if hasattr(request.state, "_current_user"):
        return request.state._current_user

    token = credentials.credentials if credentials else None

    if not token:
        raise AuthError("Missing authentication token")

    payload = decode_token(token)
    if not payload or payload.get("type") != "access":
        raise AuthError("Invalid or expired token")

    user_id = payload.get("sub")
    if not user_id:
        raise AuthError("Invalid token payload")

    user = await get_users_col().find_one({"_id": user_id, "is_active": True})
    if not user:
        raise AuthError("User not found or deactivated")

    request.state._current_user = user
    return user


def role_required(*roles: UserRole):
    async def _guard(current_user: dict = Depends(get_current_user)) -> dict:
        if current_user.get("role") not in [r.value for r in roles]:
            raise ForbiddenError()
        return current_user

    return _guard


require_client = role_required(UserRole.CLIENT)
require_lawyer = role_required(UserRole.LAWYER)
require_admin = role_required(UserRole.ADMIN)
require_client_or_lawyer = role_required(UserRole.CLIENT, UserRole.LAWYER)
