"""
Investigator Assignment/Queue API routes for the Insurance Fraud Detection Platform.
Handles assignment creation, queue management, status updates, and investigator workload.
"""
import logging
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Query

from src.api.database import supabase
from src.api.models import AssignmentCreate, AssignmentResponse, AssignmentUpdate

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/assignments", tags=["Assignments & Queues"])


# PUBLIC_INTERFACE
@router.get(
    "",
    response_model=List[AssignmentResponse],
    summary="List assignments",
    description="Retrieve investigator assignments with optional filtering by investigator, status, or claim.",
)
def list_assignments(
    investigator_id: Optional[str] = Query(None, description="Filter by investigator UUID"),
    status: Optional[str] = Query(None, description="Filter by assignment status"),
    claim_id: Optional[str] = Query(None, description="Filter by claim UUID"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    """List investigator assignments with filters.

    Args:
        investigator_id: Filter by investigator.
        status: Filter by assignment status.
        claim_id: Filter by claim.
        limit: Max results.
        offset: Pagination offset.

    Returns:
        List of assignment objects.
    """
    try:
        query = supabase.table("investigator_assignments").select("*")
        if investigator_id:
            query = query.eq("investigator_id", investigator_id)
        if status:
            query = query.eq("status", status)
        if claim_id:
            query = query.eq("claim_id", claim_id)
        query = query.order("assigned_at", desc=True).range(offset, offset + limit - 1)
        resp = query.execute()
        return resp.data or []
    except Exception as e:
        logger.error(f"Error listing assignments: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to list assignments: {str(e)}")


# PUBLIC_INTERFACE
# NOTE: This route MUST be defined BEFORE /{assignment_id} to prevent
# "queue" from being captured as an assignment_id path parameter.
@router.get(
    "/queue/{investigator_id}",
    response_model=List[AssignmentResponse],
    summary="Get investigator queue",
    description="Retrieve the pending/active assignment queue for a specific investigator.",
)
def get_investigator_queue(investigator_id: str):
    """Get the work queue for a specific investigator.

    Returns pending and in-progress assignments ordered by priority.

    Args:
        investigator_id: UUID of the investigator.

    Returns:
        List of active assignments.
    """
    try:
        resp = (
            supabase.table("investigator_assignments")
            .select("*")
            .eq("investigator_id", investigator_id)
            .in_("status", ["pending", "accepted", "in_progress"])
            .order("priority", desc=False)
            .execute()
        )
        return resp.data or []
    except Exception as e:
        logger.error(f"Error getting queue for investigator {investigator_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get queue: {str(e)}")


# PUBLIC_INTERFACE
@router.get(
    "/{assignment_id}",
    response_model=AssignmentResponse,
    summary="Get an assignment",
    description="Retrieve a specific investigator assignment by its UUID.",
)
def get_assignment(assignment_id: str):
    """Get a single assignment by ID.

    Args:
        assignment_id: UUID of the assignment.

    Returns:
        Assignment object.
    """
    try:
        resp = supabase.table("investigator_assignments").select("*").eq("id", assignment_id).execute()
        if not resp.data:
            raise HTTPException(status_code=404, detail="Assignment not found")
        return resp.data[0]
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting assignment {assignment_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get assignment: {str(e)}")


# PUBLIC_INTERFACE
@router.post(
    "",
    response_model=AssignmentResponse,
    status_code=201,
    summary="Create an assignment",
    description="Assign a claim to an investigator for fraud investigation.",
)
def create_assignment(assignment: AssignmentCreate):
    """Create a new investigator assignment.

    Also updates the claim's assigned_investigator_id and status.

    Args:
        assignment: Assignment creation data.

    Returns:
        Created assignment object.
    """
    try:
        data = assignment.model_dump(exclude_none=True)
        resp = supabase.table("investigator_assignments").insert(data).execute()
        if not resp.data:
            raise HTTPException(status_code=500, detail="Failed to create assignment")

        # Update the claim with the assigned investigator and set status to investigating
        try:
            supabase.table("claims").update({
                "assigned_investigator_id": assignment.investigator_id,
                "status": "investigating",
            }).eq("id", assignment.claim_id).execute()
        except Exception as ue:
            logger.warning(f"Failed to update claim assignment: {ue}")

        # Increment investigator caseload
        try:
            inv_resp = supabase.table("users").select("current_caseload").eq("id", assignment.investigator_id).execute()
            if inv_resp.data:
                current = inv_resp.data[0].get("current_caseload", 0) or 0
                supabase.table("users").update({
                    "current_caseload": current + 1
                }).eq("id", assignment.investigator_id).execute()
        except Exception as ce:
            logger.warning(f"Failed to update investigator caseload: {ce}")

        return resp.data[0]
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creating assignment: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to create assignment: {str(e)}")


# PUBLIC_INTERFACE
@router.put(
    "/{assignment_id}",
    response_model=AssignmentResponse,
    summary="Update an assignment",
    description="Update the status, priority, or notes of an investigator assignment.",
)
def update_assignment(assignment_id: str, assignment: AssignmentUpdate):
    """Update an existing assignment.

    Args:
        assignment_id: UUID of the assignment.
        assignment: Fields to update.

    Returns:
        Updated assignment object.
    """
    try:
        data = assignment.model_dump(exclude_none=True)
        if not data:
            raise HTTPException(status_code=400, detail="No fields to update")

        # Add timestamps based on status changes
        if data.get("status") == "accepted":
            data["accepted_at"] = "now()"
        elif data.get("status") == "completed":
            data["completed_at"] = "now()"

        resp = supabase.table("investigator_assignments").update(data).eq("id", assignment_id).execute()
        if not resp.data:
            raise HTTPException(status_code=404, detail="Assignment not found")
        return resp.data[0]
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating assignment {assignment_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to update assignment: {str(e)}")
