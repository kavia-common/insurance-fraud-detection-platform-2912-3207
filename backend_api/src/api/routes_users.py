"""
Users API routes for the Insurance Fraud Detection Platform.
Provides endpoints for listing and retrieving user (investigator/manager) data.
"""
import logging
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Query

from src.api.database import supabase
from src.api.models import UserResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/users", tags=["Users"])


# PUBLIC_INTERFACE
@router.get(
    "",
    response_model=List[UserResponse],
    summary="List users",
    description="Retrieve all users with optional filtering by role and active status.",
)
def list_users(
    role: Optional[str] = Query(None, description="Filter by user role: investigator, manager, admin"),
    is_active: Optional[bool] = Query(None, description="Filter by active status"),
):
    """List users with optional filters.

    Args:
        role: Filter by user role.
        is_active: Filter by active/inactive status.

    Returns:
        List of user objects.
    """
    try:
        query = supabase.table("users").select("*")
        if role:
            query = query.eq("role", role)
        if is_active is not None:
            query = query.eq("is_active", is_active)
        query = query.order("full_name", desc=False)
        resp = query.execute()
        return resp.data or []
    except Exception as e:
        logger.error(f"Error listing users: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to list users: {str(e)}")


# PUBLIC_INTERFACE
@router.get(
    "/investigators",
    response_model=List[UserResponse],
    summary="List investigators",
    description="Retrieve all active investigators and their current caseload.",
)
def list_investigators():
    """List all active investigators.

    Returns:
        List of investigator user objects with caseload info.
    """
    try:
        resp = (
            supabase.table("users")
            .select("*")
            .eq("role", "investigator")
            .eq("is_active", True)
            .order("current_caseload", desc=False)
            .execute()
        )
        return resp.data or []
    except Exception as e:
        logger.error(f"Error listing investigators: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to list investigators: {str(e)}")


# PUBLIC_INTERFACE
@router.get(
    "/{user_id}",
    response_model=UserResponse,
    summary="Get a user",
    description="Retrieve a specific user by their UUID.",
)
def get_user(user_id: str):
    """Get a single user by ID.

    Args:
        user_id: UUID of the user.

    Returns:
        User object.
    """
    try:
        resp = supabase.table("users").select("*").eq("id", user_id).execute()
        if not resp.data:
            raise HTTPException(status_code=404, detail="User not found")
        return resp.data[0]
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting user {user_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get user: {str(e)}")
