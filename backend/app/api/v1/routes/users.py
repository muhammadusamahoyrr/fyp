from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.dependencies import get_current_user, require_admin, require_lawyer
from app.schemas.user import (
    LawyerProfileUpdate,
    MessageResponse,
    PasswordChange,
    UserProfileResponse,
    UserUpdate,
)
from app.services import user_service

router = APIRouter(prefix="/users", tags=["users"])


@router.get("/me", response_model=UserProfileResponse)
async def get_me(current_user: dict = Depends(get_current_user)):
    return await user_service.get_profile(current_user["_id"])


@router.patch("/me", response_model=UserProfileResponse)
async def update_me(
    body: UserUpdate,
    current_user: dict = Depends(get_current_user),
):
    updates = body.model_dump(exclude_none=True)
    return await user_service.update_profile(current_user["_id"], updates)


@router.patch("/me/password", response_model=MessageResponse)
async def change_password(
    body: PasswordChange,
    current_user: dict = Depends(get_current_user),
):
    await user_service.change_password(current_user["_id"], body.current_password, body.new_password)
    return {"message": "Password updated successfully"}


class AccountClosure(BaseModel):
    # Required. Closure is irreversible and is precisely what someone with a
    # borrowed session would do for spite.
    password: str


@router.post("/me/close")
async def close_account(
    body: AccountClosure,
    current_user: dict = Depends(get_current_user),
):
    """Close your own account: revoke access and erase personal details.

    Replaces a UI button that announced "Your account has been deleted" after a
    two-second timer and called nothing at all.

    This does NOT hard-delete. Payments are financial records, provenance is an
    audit trail, and a lawyer's case history evidences obligations to clients who
    did not ask for anything to be erased — so the identifying data is
    overwritten and the skeleton kept, rather than the row removed and every
    reference to it orphaned. Refuses while engagements or payments are still
    live, and says which.
    """
    return await user_service.close_account(current_user["_id"], body.password)


@router.patch("/me/lawyer-profile", response_model=UserProfileResponse)
async def update_lawyer_profile(
    body: LawyerProfileUpdate,
    current_user: dict = Depends(require_lawyer),  # lawyers only — not clients
):
    updates = body.model_dump(exclude_none=True)
    return await user_service.update_lawyer_profile(current_user["_id"], updates)


@router.get("/{user_id}", response_model=UserProfileResponse)
async def get_user(
    user_id: str,
    current_user: dict = Depends(require_admin),  # admin-only: was leaking any user's contact info
):
    # Clients/lawyers view each other through the public /lawyers/{id} endpoint;
    # this full-profile route is restricted to admins.
    return await user_service.get_profile(user_id)
