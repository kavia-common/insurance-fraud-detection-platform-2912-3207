"""
Claim Outcomes API routes for the Insurance Fraud Detection Platform.
Handles logging and retrieval of fraud investigation outcomes and resolutions.
"""
import logging
from datetime import date
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Query

from src.api.database import supabase
from src.api.models import OutcomeCreate, OutcomeResponse, OutcomeUpdate

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/outcomes", tags=["Outcomes"])


# PUBLIC_INTERFACE
@router.get(
    "",
    response_model=List[OutcomeResponse],
    summary="List claim outcomes",
    description="Retrieve all claim investigation outcomes with optional filtering.",
)
def list_outcomes(
    outcome: Optional[str] = Query(None, description="Filter by outcome type"),
    investigator_id: Optional[str] = Query(None, description="Filter by investigator UUID"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    """List claim outcomes with optional filters.

    Args:
        outcome: Filter by outcome type.
        investigator_id: Filter by investigator.
        limit: Max results.
        offset: Pagination offset.

    Returns:
        List of outcome objects.
    """
    try:
        query = supabase.table("claim_outcomes").select("*")
        if outcome:
            query = query.eq("outcome", outcome)
        if investigator_id:
            query = query.eq("investigator_id", investigator_id)
        query = query.order("created_at", desc=True).range(offset, offset + limit - 1)
        resp = query.execute()
        return resp.data or []
    except Exception as e:
        logger.error(f"Error listing outcomes: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to list outcomes: {str(e)}")


# PUBLIC_INTERFACE
@router.get(
    "/{outcome_id}",
    response_model=OutcomeResponse,
    summary="Get a claim outcome",
    description="Retrieve a specific claim outcome by its UUID.",
)
def get_outcome(outcome_id: str):
    """Get a single claim outcome by ID.

    Args:
        outcome_id: UUID of the outcome.

    Returns:
        Outcome object.
    """
    try:
        resp = supabase.table("claim_outcomes").select("*").eq("id", outcome_id).execute()
        if not resp.data:
            raise HTTPException(status_code=404, detail="Outcome not found")
        return resp.data[0]
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting outcome {outcome_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get outcome: {str(e)}")


# PUBLIC_INTERFACE
@router.get(
    "/claim/{claim_id}",
    response_model=Optional[OutcomeResponse],
    summary="Get outcome for a claim",
    description="Retrieve the investigation outcome for a specific claim.",
)
def get_outcome_by_claim(claim_id: str):
    """Get the outcome for a specific claim.

    Args:
        claim_id: UUID of the claim.

    Returns:
        Outcome object or None.
    """
    try:
        resp = supabase.table("claim_outcomes").select("*").eq("claim_id", claim_id).execute()
        if not resp.data:
            return None
        return resp.data[0]
    except Exception as e:
        logger.error(f"Error getting outcome for claim {claim_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get outcome: {str(e)}")


# PUBLIC_INTERFACE
@router.post(
    "",
    response_model=OutcomeResponse,
    status_code=201,
    summary="Log a claim outcome",
    description="Record the investigation outcome for a claim, including fraud determination and recovery details.",
)
def create_outcome(outcome: OutcomeCreate):
    """Create/log a fraud investigation outcome.

    Updates the associated claim status based on the outcome type.

    Args:
        outcome: Outcome creation data.

    Returns:
        Created outcome object.
    """
    try:
        data = outcome.model_dump(exclude_none=True)
        # Convert enum to string value
        if "outcome" in data and hasattr(data["outcome"], "value"):
            data["outcome"] = data["outcome"].value
        # Convert date to string
        if "resolution_date" in data and isinstance(data["resolution_date"], date):
            data["resolution_date"] = data["resolution_date"].isoformat()

        resp = supabase.table("claim_outcomes").insert(data).execute()
        if not resp.data:
            raise HTTPException(status_code=500, detail="Failed to create outcome")

        # Update the claim status based on outcome
        outcome_val = data.get("outcome", "pending")
        claim_status_map = {
            "confirmed_fraud": "closed_confirmed_fraud",
            "legitimate": "closed_legitimate",
            "insufficient_evidence": "closed_insufficient_evidence",
            "referred_to_law_enforcement": "closed_confirmed_fraud",
            "pending": "investigating",
        }
        new_status = claim_status_map.get(outcome_val, "investigating")
        try:
            supabase.table("claims").update({
                "status": new_status
            }).eq("id", outcome.claim_id).execute()
        except Exception as ue:
            logger.warning(f"Failed to update claim status after outcome: {ue}")

        # Decrement investigator caseload on completion
        if outcome_val not in ("pending",):
            try:
                inv_resp = supabase.table("users").select("current_caseload").eq(
                    "id", outcome.investigator_id
                ).execute()
                if inv_resp.data:
                    current = inv_resp.data[0].get("current_caseload", 0) or 0
                    new_load = max(0, current - 1)
                    supabase.table("users").update({
                        "current_caseload": new_load
                    }).eq("id", outcome.investigator_id).execute()
            except Exception as ce:
                logger.warning(f"Failed to update investigator caseload: {ce}")

        return resp.data[0]
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creating outcome: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to create outcome: {str(e)}")


# PUBLIC_INTERFACE
@router.put(
    "/{outcome_id}",
    response_model=OutcomeResponse,
    summary="Update a claim outcome",
    description="Update an existing claim investigation outcome.",
)
def update_outcome(outcome_id: str, outcome: OutcomeUpdate):
    """Update an existing outcome.

    Args:
        outcome_id: UUID of the outcome.
        outcome: Fields to update.

    Returns:
        Updated outcome object.
    """
    try:
        data = outcome.model_dump(exclude_none=True)
        if not data:
            raise HTTPException(status_code=400, detail="No fields to update")
        # Convert enum/date
        if "outcome" in data and hasattr(data["outcome"], "value"):
            data["outcome"] = data["outcome"].value
        if "resolution_date" in data and isinstance(data["resolution_date"], date):
            data["resolution_date"] = data["resolution_date"].isoformat()

        resp = supabase.table("claim_outcomes").update(data).eq("id", outcome_id).execute()
        if not resp.data:
            raise HTTPException(status_code=404, detail="Outcome not found")
        return resp.data[0]
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating outcome {outcome_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to update outcome: {str(e)}")
