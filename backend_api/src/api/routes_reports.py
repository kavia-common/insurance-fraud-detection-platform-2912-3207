"""
Reporting and Dashboard API routes for the Insurance Fraud Detection Platform.
Provides endpoints for dashboard summaries, filtered reports, and report generation/storage.
"""
import logging
from typing import Dict, List

from fastapi import APIRouter, HTTPException, Query

from src.api.database import supabase
from src.api.models import DashboardSummary, ReportFilters, ReportResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/reports", tags=["Reporting"])


# PUBLIC_INTERFACE
@router.get(
    "/dashboard",
    response_model=DashboardSummary,
    summary="Get dashboard summary",
    description="Retrieve aggregated dashboard statistics including claim counts, fraud stats, and risk distribution.",
)
def get_dashboard_summary():
    """Get dashboard summary statistics.

    Computes aggregated metrics from claims, outcomes, and assignments.

    Returns:
        DashboardSummary with totals, averages, and breakdowns.
    """
    try:
        # Get all claims for aggregation
        claims_resp = supabase.table("claims").select(
            "id,status,fraud_score,risk_level,claim_amount"
        ).execute()
        claims = claims_resp.data or []

        total_claims = len(claims)
        flagged = sum(1 for c in claims if c.get("status") == "flagged")
        high_risk = sum(1 for c in claims if c.get("risk_level") == "high")
        under_investigation = sum(
            1 for c in claims if c.get("status") == "investigating"
        )

        # Compute average fraud score
        scores = [c.get("fraud_score", 0) or 0 for c in claims]
        avg_score = round(sum(scores) / max(len(scores), 1), 1)

        # Status breakdown
        claims_by_status: Dict[str, int] = {}
        for c in claims:
            s = c.get("status", "unknown")
            claims_by_status[s] = claims_by_status.get(s, 0) + 1

        # Risk breakdown
        claims_by_risk: Dict[str, int] = {}
        for c in claims:
            r = c.get("risk_level", "unknown") or "unknown"
            claims_by_risk[r] = claims_by_risk.get(r, 0) + 1

        # Get outcomes for confirmed fraud count and recovery
        outcomes_resp = supabase.table("claim_outcomes").select(
            "outcome,recovery_amount"
        ).execute()
        outcomes = outcomes_resp.data or []
        confirmed_fraud = sum(1 for o in outcomes if o.get("outcome") == "confirmed_fraud")
        total_recovery = sum(float(o.get("recovery_amount", 0) or 0) for o in outcomes)

        return DashboardSummary(
            total_claims=total_claims,
            flagged_claims=flagged,
            high_risk_claims=high_risk,
            under_investigation=under_investigation,
            confirmed_fraud=confirmed_fraud,
            total_recovery=total_recovery,
            avg_fraud_score=avg_score,
            claims_by_status=claims_by_status,
            claims_by_risk=claims_by_risk,
        )
    except Exception as e:
        logger.error(f"Error building dashboard summary: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get dashboard: {str(e)}")


# PUBLIC_INTERFACE
@router.post(
    "/generate",
    response_model=ReportResponse,
    summary="Generate a filtered report",
    description="Generate a report based on specified filters (date range, status, risk level, investigator, claim type).",
)
def generate_report(filters: ReportFilters):
    """Generate a filtered report and optionally save a snapshot.

    Args:
        filters: Report filter criteria.

    Returns:
        ReportResponse with filtered data and statistics.
    """
    try:
        query = supabase.table("claims").select("*")

        if filters.status:
            query = query.eq("status", filters.status)
        if filters.risk_level:
            query = query.eq("risk_level", filters.risk_level)
        if filters.investigator_id:
            query = query.eq("assigned_investigator_id", filters.investigator_id)
        if filters.claim_type:
            query = query.eq("claim_type", filters.claim_type)
        if filters.start_date:
            query = query.gte("filed_date", filters.start_date)
        if filters.end_date:
            query = query.lte("filed_date", filters.end_date)

        query = query.order("filed_date", desc=True)
        resp = query.execute()
        claims = resp.data or []

        # Compute report statistics
        total = len(claims)
        scores = [c.get("fraud_score", 0) or 0 for c in claims]
        avg_score = round(sum(scores) / max(total, 1), 1)
        total_amount = sum(float(c.get("claim_amount", 0) or 0) for c in claims)

        status_dist: Dict[str, int] = {}
        risk_dist: Dict[str, int] = {}
        type_dist: Dict[str, int] = {}

        for c in claims:
            s = c.get("status", "unknown")
            status_dist[s] = status_dist.get(s, 0) + 1
            r = c.get("risk_level", "unknown") or "unknown"
            risk_dist[r] = risk_dist.get(r, 0) + 1
            t = c.get("claim_type", "unknown")
            type_dist[t] = type_dist.get(t, 0) + 1

        report_data = {
            "total_claims": total,
            "average_fraud_score": avg_score,
            "total_claim_amount": total_amount,
            "status_distribution": status_dist,
            "risk_distribution": risk_dist,
            "type_distribution": type_dist,
            "claims": claims,
        }

        # Save report snapshot
        filter_dict = filters.model_dump(exclude_none=True)
        try:
            snap_resp = supabase.table("report_snapshots").insert({
                "report_type": "filtered_claims",
                "filters": filter_dict,
                "data": report_data,
            }).execute()
            report_id = snap_resp.data[0]["id"] if snap_resp.data else None
        except Exception as se:
            logger.warning(f"Failed to save report snapshot: {se}")
            report_id = None

        return ReportResponse(
            id=report_id,
            report_type="filtered_claims",
            filters=filter_dict,
            data=report_data,
        )
    except Exception as e:
        logger.error(f"Error generating report: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to generate report: {str(e)}")


# PUBLIC_INTERFACE
@router.get(
    "/history",
    response_model=List[ReportResponse],
    summary="List saved reports",
    description="Retrieve previously generated and saved report snapshots.",
)
def list_report_history(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    """List previously saved report snapshots.

    Args:
        limit: Max results.
        offset: Pagination offset.

    Returns:
        List of saved report snapshots.
    """
    try:
        resp = (
            supabase.table("report_snapshots")
            .select("*")
            .order("generated_at", desc=True)
            .range(offset, offset + limit - 1)
            .execute()
        )
        return resp.data or []
    except Exception as e:
        logger.error(f"Error listing reports: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to list reports: {str(e)}")


# PUBLIC_INTERFACE
@router.get(
    "/{report_id}",
    response_model=ReportResponse,
    summary="Get a saved report",
    description="Retrieve a specific saved report snapshot by its UUID.",
)
def get_report(report_id: str):
    """Get a specific saved report by ID.

    Args:
        report_id: UUID of the report snapshot.

    Returns:
        Report data.
    """
    try:
        resp = supabase.table("report_snapshots").select("*").eq("id", report_id).execute()
        if not resp.data:
            raise HTTPException(status_code=404, detail="Report not found")
        return resp.data[0]
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting report {report_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get report: {str(e)}")
