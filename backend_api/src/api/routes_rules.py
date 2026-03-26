"""
Fraud Rules CRUD API routes for the Insurance Fraud Detection Platform.
Provides endpoints for creating, reading, updating, and deleting fraud detection rules.
"""
import logging
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Query

from src.api.database import supabase
from src.api.models import FraudRuleCreate, FraudRuleResponse, FraudRuleUpdate

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/rules", tags=["Fraud Rules"])


# PUBLIC_INTERFACE
@router.get(
    "",
    response_model=List[FraudRuleResponse],
    summary="List all fraud rules",
    description="Retrieve all fraud detection rules with optional filtering by category and active status.",
)
def list_rules(
    category: Optional[str] = Query(None, description="Filter by rule category"),
    is_active: Optional[bool] = Query(None, description="Filter by active status"),
):
    """List all fraud detection rules.

    Args:
        category: Optional filter by rule category.
        is_active: Optional filter by active/inactive status.

    Returns:
        List of fraud rules.
    """
    try:
        query = supabase.table("fraud_rules").select("*")
        if category:
            query = query.eq("category", category)
        if is_active is not None:
            query = query.eq("is_active", is_active)
        query = query.order("created_at", desc=True)
        resp = query.execute()
        return resp.data or []
    except Exception as e:
        logger.error(f"Error listing rules: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to list rules: {str(e)}")


# PUBLIC_INTERFACE
@router.get(
    "/{rule_id}",
    response_model=FraudRuleResponse,
    summary="Get a fraud rule",
    description="Retrieve a specific fraud detection rule by its UUID.",
)
def get_rule(rule_id: str):
    """Get a single fraud rule by ID.

    Args:
        rule_id: UUID of the rule.

    Returns:
        Fraud rule object.
    """
    try:
        resp = supabase.table("fraud_rules").select("*").eq("id", rule_id).execute()
        if not resp.data:
            raise HTTPException(status_code=404, detail="Rule not found")
        return resp.data[0]
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting rule {rule_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get rule: {str(e)}")


# PUBLIC_INTERFACE
@router.post(
    "",
    response_model=FraudRuleResponse,
    status_code=201,
    summary="Create a fraud rule",
    description="Create a new configurable fraud detection rule with category, condition config, and score weight.",
)
def create_rule(rule: FraudRuleCreate):
    """Create a new fraud detection rule.

    Args:
        rule: Rule creation data including name, category, config, and weight.

    Returns:
        Created rule object.
    """
    try:
        data = rule.model_dump()
        # Convert enum to string value
        if "category" in data:
            data["category"] = data["category"].value if hasattr(data["category"], "value") else data["category"]
        resp = supabase.table("fraud_rules").insert(data).execute()
        if not resp.data:
            raise HTTPException(status_code=500, detail="Failed to create rule")
        return resp.data[0]
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creating rule: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to create rule: {str(e)}")


# PUBLIC_INTERFACE
@router.put(
    "/{rule_id}",
    response_model=FraudRuleResponse,
    summary="Update a fraud rule",
    description="Update an existing fraud detection rule's configuration, weight, or active status.",
)
def update_rule(rule_id: str, rule: FraudRuleUpdate):
    """Update an existing fraud rule.

    Args:
        rule_id: UUID of the rule to update.
        rule: Fields to update.

    Returns:
        Updated rule object.
    """
    try:
        data = rule.model_dump(exclude_none=True)
        if not data:
            raise HTTPException(status_code=400, detail="No fields to update")
        # Convert enum to string value
        if "category" in data and hasattr(data["category"], "value"):
            data["category"] = data["category"].value
        resp = supabase.table("fraud_rules").update(data).eq("id", rule_id).execute()
        if not resp.data:
            raise HTTPException(status_code=404, detail="Rule not found")
        return resp.data[0]
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating rule {rule_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to update rule: {str(e)}")


# PUBLIC_INTERFACE
@router.delete(
    "/{rule_id}",
    summary="Delete a fraud rule",
    description="Delete a fraud detection rule by its UUID.",
)
def delete_rule(rule_id: str):
    """Delete a fraud rule.

    Args:
        rule_id: UUID of the rule to delete.

    Returns:
        Confirmation message.
    """
    try:
        resp = supabase.table("fraud_rules").delete().eq("id", rule_id).execute()
        if not resp.data:
            raise HTTPException(status_code=404, detail="Rule not found")
        return {"message": "Rule deleted", "id": rule_id}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting rule {rule_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to delete rule: {str(e)}")
