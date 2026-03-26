"""
Claims API routes for the Insurance Fraud Detection Platform.
Handles claim ingestion (CSV upload and manual entry), retrieval, updating,
fraud scoring trigger, and claim detail endpoints.

IMPORTANT — Route ordering:
Static paths (e.g. /upload-csv) MUST be registered BEFORE parameterised
paths (e.g. /{claim_id}) so FastAPI does not treat the static segment as
a path-parameter value.
"""
import csv
import io
import json
import logging
import uuid
from datetime import date
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, File, HTTPException, Query, UploadFile

from src.api.database import supabase
from src.api.fraud_engine import score_and_save
from src.api.models import (
    CSVUploadResponse,
    ClaimCreate,
    ClaimResponse,
    ClaimUpdate,
    FraudSignalResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/claims", tags=["Claims"])


def _generate_claim_number() -> str:
    """Generate a unique claim number."""
    return f"CLM-{uuid.uuid4().hex[:8].upper()}"


def _sanitize_claim_row(row: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize a raw claim row from the database so it passes Pydantic validation.

    Handles:
    - JSONB ``third_parties`` (list/dict) converted to a comma-separated string.
    - Null values for required fields replaced with sensible defaults.
    - Type coercion for numeric / boolean fields that may arrive as strings or
      unexpected types from manual SQL inserts.

    Args:
        row: Raw dictionary from a Supabase query result.

    Returns:
        A cleaned dictionary safe for ``ClaimResponse`` construction.
    """
    if not row:
        return row

    sanitized = dict(row)

    # --- third_parties: may be a JSONB list/dict; ensure it is a string or None ---
    tp = sanitized.get("third_parties")
    if tp is not None:
        if isinstance(tp, (list, tuple)):
            # Convert list of party names to comma-separated string
            sanitized["third_parties"] = ", ".join(str(item) for item in tp)
        elif isinstance(tp, dict):
            # Convert dict to JSON string representation
            try:
                sanitized["third_parties"] = json.dumps(tp)
            except (TypeError, ValueError):
                sanitized["third_parties"] = str(tp)
        elif not isinstance(tp, str):
            sanitized["third_parties"] = str(tp)

    # --- Required string fields: provide safe defaults for nulls ---
    if not sanitized.get("claim_number"):
        sanitized["claim_number"] = _generate_claim_number()

    if not sanitized.get("claim_type"):
        sanitized["claim_type"] = "Unknown"

    if not sanitized.get("incident_date"):
        sanitized["incident_date"] = date.today().isoformat()

    # --- claim_amount: ensure it is a float ---
    try:
        sanitized["claim_amount"] = float(sanitized.get("claim_amount") or 0)
    except (TypeError, ValueError):
        sanitized["claim_amount"] = 0.0

    # --- fraud_score: ensure int or None ---
    fs = sanitized.get("fraud_score")
    if fs is not None:
        try:
            sanitized["fraud_score"] = int(fs)
        except (TypeError, ValueError):
            sanitized["fraud_score"] = 0

    # --- witnesses: ensure int or None ---
    w = sanitized.get("witnesses")
    if w is not None:
        try:
            sanitized["witnesses"] = int(w)
        except (TypeError, ValueError):
            sanitized["witnesses"] = 0

    # --- police_report_filed: ensure bool or None ---
    prf = sanitized.get("police_report_filed")
    if prf is not None and not isinstance(prf, bool):
        if isinstance(prf, str):
            sanitized["police_report_filed"] = prf.lower() in ("true", "1", "yes", "t")
        else:
            sanitized["police_report_filed"] = bool(prf)

    # --- Stringify date/datetime objects that Pydantic expects as strings ---
    for date_field in ("incident_date", "filed_date", "created_at", "updated_at"):
        val = sanitized.get(date_field)
        if val is not None and not isinstance(val, str):
            sanitized[date_field] = str(val)

    return sanitized


# ---------------------------------------------------------------------------
# Collection-level routes (no path parameter) — always safe at any position
# ---------------------------------------------------------------------------

# PUBLIC_INTERFACE
@router.get(
    "",
    response_model=List[ClaimResponse],
    summary="List all claims",
    description="Retrieve a paginated list of claims with optional filters for status, risk level, and search.",
)
def list_claims(
    status: Optional[str] = Query(None, description="Filter by claim status"),
    risk_level: Optional[str] = Query(None, description="Filter by risk level: low/medium/high"),
    search: Optional[str] = Query(None, description="Search in claim_number or description"),
    limit: int = Query(50, description="Max results", ge=1, le=200),
    offset: int = Query(0, description="Offset for pagination", ge=0),
):
    """List claims with optional filtering and pagination.

    Args:
        status: Filter by claim status enum value.
        risk_level: Filter by risk level (low, medium, high).
        search: Free-text search on claim_number or description.
        limit: Maximum number of results to return.
        offset: Pagination offset.

    Returns:
        List of claim objects.
    """
    try:
        query = supabase.table("claims").select("*")
        if status:
            query = query.eq("status", status)
        if risk_level:
            query = query.eq("risk_level", risk_level)
        if search:
            query = query.or_(
                f"claim_number.ilike.%{search}%,description.ilike.%{search}%"
            )
        query = query.order("created_at", desc=True).range(offset, offset + limit - 1)
        resp = query.execute()
        rows = resp.data or []
        # Sanitize each row to handle manually-inserted data with unexpected
        # types (e.g. JSONB third_parties, null required fields).
        return [_sanitize_claim_row(row) for row in rows]
    except Exception as e:
        logger.error(f"Error listing claims: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to list claims: {str(e)}")


# PUBLIC_INTERFACE
@router.post(
    "",
    response_model=ClaimResponse,
    status_code=201,
    summary="Create a new claim manually",
    description="Manually create a new insurance claim and trigger fraud scoring.",
)
def create_claim(claim: ClaimCreate):
    """Create a new claim via manual entry and run fraud scoring.

    Args:
        claim: Claim creation data.

    Returns:
        Created claim with fraud score.
    """
    try:
        data = claim.model_dump(exclude_none=True)
        # Convert date objects to strings for JSON serialization
        for key in ["incident_date", "filed_date"]:
            if key in data and isinstance(data[key], date):
                data[key] = data[key].isoformat()
        if "filed_date" not in data:
            data["filed_date"] = date.today().isoformat()
        data["ingestion_source"] = "manual"
        data["status"] = "new"

        resp = supabase.table("claims").insert(data).execute()
        if not resp.data:
            raise HTTPException(status_code=500, detail="Failed to insert claim")

        created_claim = resp.data[0]
        claim_id = created_claim["id"]

        # Run fraud scoring
        fraud_score, signals = score_and_save(claim_id, created_claim)
        # Re-fetch to get updated score
        updated = supabase.table("claims").select("*").eq("id", claim_id).execute()
        result = updated.data[0] if updated.data else created_claim
        return _sanitize_claim_row(result)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creating claim: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to create claim: {str(e)}")


# ---------------------------------------------------------------------------
# Static sub-paths — MUST come before /{claim_id} to avoid shadowing
# ---------------------------------------------------------------------------

# PUBLIC_INTERFACE
@router.post(
    "/upload-csv",
    response_model=CSVUploadResponse,
    summary="Upload claims via CSV",
    description=(
        "Ingest multiple claims from a CSV file. Expected columns: "
        "claim_number, claimant_name, claimant_address, policy_number, "
        "claim_type, claim_amount, incident_date, description, "
        "location, police_report_filed, witnesses, third_parties. "
        "Optional columns: policy_id, policyholder_id, police_report_number, filed_date."
    ),
)
async def upload_csv(file: UploadFile = File(...)):
    """Ingest claims from a CSV file upload.

    Processes each row, creates claims, and runs fraud scoring on each.
    Supports new AC1 fields: claimant_name, claimant_address, policy_number, third_parties.

    Args:
        file: Uploaded CSV file.

    Returns:
        Summary of ingestion results including created claim IDs and any errors.
    """
    if not file.filename or not file.filename.endswith(".csv"):
        raise HTTPException(status_code=400, detail="File must be a CSV")

    try:
        content = await file.read()
        text = content.decode("utf-8")
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Could not read file: {str(e)}")

    reader = csv.DictReader(io.StringIO(text))
    total_rows = 0
    success_count = 0
    failed_rows = 0
    errors = []
    claim_ids = []

    for row_num, row in enumerate(reader, start=1):
        total_rows += 1
        try:
            # Map CSV columns to claim fields
            claim_data = {
                "claim_number": row.get("claim_number", _generate_claim_number()),
                "claim_type": row.get("claim_type", "Unknown"),
                "claim_amount": float(row.get("claim_amount", 0)),
                "incident_date": row.get("incident_date", date.today().isoformat()),
                "filed_date": row.get("filed_date", date.today().isoformat()),
                "description": row.get("description", ""),
                "location": row.get("location", ""),
                "police_report_filed": row.get("police_report_filed", "false").lower() in ("true", "1", "yes"),
                "witnesses": int(row.get("witnesses", 0)),
                "ingestion_source": "csv",
                "status": "new",
            }

            # New AC1 ingestion fields
            if row.get("claimant_name"):
                claim_data["claimant_name"] = row["claimant_name"].strip()
            if row.get("claimant_address"):
                claim_data["claimant_address"] = row["claimant_address"].strip()
            if row.get("policy_number"):
                claim_data["policy_number"] = row["policy_number"].strip()
            if row.get("third_parties"):
                claim_data["third_parties"] = row["third_parties"].strip()

            # Optional reference ID fields
            if row.get("policy_id"):
                claim_data["policy_id"] = row["policy_id"]
            if row.get("policyholder_id"):
                claim_data["policyholder_id"] = row["policyholder_id"]
            if row.get("police_report_number"):
                claim_data["police_report_number"] = row["police_report_number"]

            resp = supabase.table("claims").insert(claim_data).execute()
            if resp.data:
                created = resp.data[0]
                cid = created["id"]
                claim_ids.append(cid)
                # Run fraud scoring
                score_and_save(cid, created)
                success_count += 1
            else:
                failed_rows += 1
                errors.append({"row": row_num, "error": "Insert returned no data"})
        except Exception as e:
            failed_rows += 1
            errors.append({"row": row_num, "error": str(e)})

    return CSVUploadResponse(
        total_rows=total_rows,
        successfully_ingested=success_count,
        failed_rows=failed_rows,
        errors=errors,
        claim_ids=claim_ids,
    )


# ---------------------------------------------------------------------------
# Parameterised routes — /{claim_id} and its sub-paths
# ---------------------------------------------------------------------------

# PUBLIC_INTERFACE
@router.get(
    "/{claim_id}",
    response_model=ClaimResponse,
    summary="Get claim details",
    description="Retrieve detailed information about a specific claim by its UUID.",
)
def get_claim(claim_id: str):
    """Get a single claim by its UUID.

    Args:
        claim_id: UUID of the claim.

    Returns:
        Claim detail object.

    Raises:
        HTTPException: If claim not found.
    """
    try:
        resp = supabase.table("claims").select("*").eq("id", claim_id).execute()
        if not resp.data:
            raise HTTPException(status_code=404, detail="Claim not found")
        return _sanitize_claim_row(resp.data[0])
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting claim {claim_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get claim: {str(e)}")


# PUBLIC_INTERFACE
@router.put(
    "/{claim_id}",
    response_model=ClaimResponse,
    summary="Update a claim",
    description="Update fields of an existing claim by its UUID.",
)
def update_claim(claim_id: str, claim: ClaimUpdate):
    """Update an existing claim.

    Args:
        claim_id: UUID of the claim to update.
        claim: Fields to update.

    Returns:
        Updated claim object.
    """
    try:
        data = claim.model_dump(exclude_none=True)
        if not data:
            raise HTTPException(status_code=400, detail="No fields to update")
        resp = supabase.table("claims").update(data).eq("id", claim_id).execute()
        if not resp.data:
            raise HTTPException(status_code=404, detail="Claim not found")
        return _sanitize_claim_row(resp.data[0])
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating claim {claim_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to update claim: {str(e)}")


# PUBLIC_INTERFACE
@router.post(
    "/{claim_id}/score",
    summary="Re-score a claim",
    description="Re-evaluate a claim against all active fraud rules and update its fraud score.",
)
def rescore_claim(claim_id: str):
    """Re-run fraud scoring on an existing claim.

    Deletes old fraud signals, re-evaluates all active rules, persists
    the new fraud_score to the claim record (risk_level is auto-computed
    by the database), and returns the updated claim state.

    Args:
        claim_id: UUID of the claim.

    Returns:
        Dict with new fraud_score, risk_level, status, and signal details.
    """
    try:
        # Fetch the claim
        claim_resp = supabase.table("claims").select("*").eq("id", claim_id).execute()
        if not claim_resp.data:
            raise HTTPException(status_code=404, detail="Claim not found")
        claim_data = claim_resp.data[0]

        # Delete old signals before re-scoring
        try:
            supabase.table("fraud_signals").delete().eq("claim_id", claim_id).execute()
        except Exception:
            logger.warning(f"Could not delete old signals for claim {claim_id}")

        # Score and persist
        fraud_score, signals = score_and_save(claim_id, claim_data)

        # Re-fetch the claim to get the DB-persisted fraud_score and the
        # auto-computed risk_level (GENERATED ALWAYS column).
        try:
            updated_resp = supabase.table("claims").select("*").eq("id", claim_id).execute()
            if updated_resp.data:
                updated_claim = updated_resp.data[0]
                risk_level = updated_claim.get("risk_level", "low")
                status = updated_claim.get("status", "new")
                persisted_score = updated_claim.get("fraud_score", fraud_score)
            else:
                # Fallback to in-memory values if re-fetch fails
                persisted_score = fraud_score
                risk_level = "high" if fraud_score >= 75 else ("medium" if fraud_score >= 40 else "low")
                status = claim_data.get("status", "new")
        except Exception as e:
            logger.warning(f"Could not re-fetch claim {claim_id} after scoring: {e}")
            persisted_score = fraud_score
            risk_level = "high" if fraud_score >= 75 else ("medium" if fraud_score >= 40 else "low")
            status = claim_data.get("status", "new")

        return {
            "claim_id": claim_id,
            "fraud_score": persisted_score,
            "risk_level": risk_level,
            "status": status,
            "signals": signals,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error rescoring claim {claim_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to rescore claim: {str(e)}")


# PUBLIC_INTERFACE
@router.get(
    "/{claim_id}/signals",
    response_model=List[FraudSignalResponse],
    summary="Get fraud signals for a claim",
    description="Retrieve all fraud signal evaluations for a specific claim, with explanations.",
)
def get_claim_signals(claim_id: str):
    """Get fraud signals/explanations for a specific claim.

    Args:
        claim_id: UUID of the claim.

    Returns:
        List of fraud signals with explanations.
    """
    try:
        resp = supabase.table("fraud_signals").select("*").eq("claim_id", claim_id).execute()
        return resp.data or []
    except Exception as e:
        logger.error(f"Error getting signals for claim {claim_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get signals: {str(e)}")
