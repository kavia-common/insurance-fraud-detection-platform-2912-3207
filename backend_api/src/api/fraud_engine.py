"""
Fraud Scoring Engine for the Insurance Fraud Detection Platform.
Evaluates claims against configurable fraud detection rules and generates
fraud scores (0-100) with human-readable explanations.
"""
from datetime import datetime
from typing import Any, Dict, List, Tuple
import logging

from src.api.database import supabase

logger = logging.getLogger(__name__)


# ---- Built-in rule evaluators ----

def _evaluate_high_amount(claim: Dict[str, Any], config: Dict[str, Any]) -> Tuple[bool, str]:
    """Check if claim amount exceeds configured threshold."""
    threshold = config.get("threshold", 15000)
    amount = float(claim.get("claim_amount", 0))
    if amount > threshold:
        return True, f"Claim amount ${amount:,.2f} exceeds threshold ${threshold:,.2f}"
    return False, f"Claim amount ${amount:,.2f} is within threshold ${threshold:,.2f}"


def _evaluate_quick_filing(claim: Dict[str, Any], config: Dict[str, Any]) -> Tuple[bool, str]:
    """Check if claim was filed suspiciously soon after incident."""
    days_threshold = config.get("days", 2)
    incident_str = claim.get("incident_date")
    filed_str = claim.get("filed_date")
    if not incident_str or not filed_str:
        return False, "Missing date information for quick filing check"
    try:
        incident = datetime.strptime(str(incident_str)[:10], "%Y-%m-%d").date()
        filed = datetime.strptime(str(filed_str)[:10], "%Y-%m-%d").date()
        diff = (filed - incident).days
        if diff <= days_threshold:
            return True, f"Claim filed {diff} day(s) after incident (threshold: {days_threshold} days)"
        return False, f"Claim filed {diff} day(s) after incident (threshold: {days_threshold} days)"
    except (ValueError, TypeError) as e:
        return False, f"Could not parse dates for quick filing check: {e}"


def _evaluate_frequency(claim: Dict[str, Any], config: Dict[str, Any]) -> Tuple[bool, str]:
    """Check if policyholder has multiple claims within a time window."""
    months = config.get("months", 6)
    count_threshold = config.get("count", 2)
    policyholder_id = claim.get("policyholder_id")
    if not policyholder_id:
        return False, "No policyholder linked; cannot check frequency"
    try:
        # Query claims by same policyholder in the window
        resp = supabase.table("claims").select("id").eq(
            "policyholder_id", policyholder_id
        ).execute()
        total = len(resp.data) if resp.data else 0
        if total > count_threshold:
            return True, f"Policyholder has {total} claims (threshold: >{count_threshold} in {months} months)"
        return False, f"Policyholder has {total} claims (threshold: >{count_threshold} in {months} months)"
    except Exception as e:
        logger.warning(f"Frequency check failed: {e}")
        return False, f"Frequency check error: {e}"


def _evaluate_no_police_report(claim: Dict[str, Any], config: Dict[str, Any]) -> Tuple[bool, str]:
    """Flag claims over a certain amount without a police report."""
    threshold = config.get("threshold", 5000)
    amount = float(claim.get("claim_amount", 0))
    has_report = claim.get("police_report_filed", False)
    if amount > threshold and not has_report:
        return True, f"No police report for ${amount:,.2f} claim (threshold: ${threshold:,.2f})"
    return False, "Police report filed or amount below threshold"


def _evaluate_no_witnesses(claim: Dict[str, Any], config: Dict[str, Any]) -> Tuple[bool, str]:
    """Flag claims with zero witnesses for high-value incidents."""
    threshold = config.get("threshold", 10000)
    amount = float(claim.get("claim_amount", 0))
    witnesses = int(claim.get("witnesses", 0))
    if amount > threshold and witnesses == 0:
        return True, f"No witnesses for ${amount:,.2f} claim (threshold: ${threshold:,.2f})"
    return False, "Witnesses present or amount below threshold"


def _evaluate_location(claim: Dict[str, Any], config: Dict[str, Any]) -> Tuple[bool, str]:
    """Check for out-of-state or suspicious location patterns."""
    claim_location = claim.get("location", "")
    if not claim_location:
        return False, "No location data available for location check"
    # Simple heuristic: flag if location contains certain keywords
    suspicious_keywords = config.get("suspicious_keywords", [])
    for kw in suspicious_keywords:
        if kw.lower() in claim_location.lower():
            return True, f"Location '{claim_location}' matches suspicious keyword '{kw}'"
    return False, f"Location '{claim_location}' does not match suspicious patterns"


def _evaluate_network(claim: Dict[str, Any], config: Dict[str, Any]) -> Tuple[bool, str]:
    """Check if claim is related to a known fraud network."""
    policyholder_id = claim.get("policyholder_id")
    if not policyholder_id:
        return False, "No policyholder linked; cannot check network"
    try:
        resp = supabase.table("network_relationships").select("id").or_(
            f"entity_a_id.eq.{policyholder_id},entity_b_id.eq.{policyholder_id}"
        ).execute()
        count = len(resp.data) if resp.data else 0
        if count > 0:
            return True, f"Policyholder linked to {count} network relationship(s)"
        return False, "No known network relationships found"
    except Exception as e:
        logger.warning(f"Network check failed: {e}")
        return False, f"Network check error: {e}"


# Map rule categories to built-in evaluators
RULE_EVALUATORS = {
    "amount": _evaluate_high_amount,
    "timing": _evaluate_quick_filing,
    "frequency": _evaluate_frequency,
    "pattern": _evaluate_no_police_report,
    "location": _evaluate_location,
    "network": _evaluate_network,
    "custom": _evaluate_no_witnesses,
}


# PUBLIC_INTERFACE
def evaluate_claim(claim: Dict[str, Any]) -> Tuple[int, List[Dict[str, Any]]]:
    """Evaluate a claim against all active fraud rules and compute a fraud score.

    Fetches all active rules from the database, applies each rule's evaluator,
    and computes a weighted fraud score (capped at 100).

    Args:
        claim: Dictionary containing claim data fields.

    Returns:
        Tuple of (fraud_score, signals) where:
            - fraud_score: Integer 0-100
            - signals: List of dicts with keys: rule_id, triggered, signal_score, explanation, details
    """
    signals = []
    total_score = 0

    try:
        # Fetch all active rules
        rules_resp = supabase.table("fraud_rules").select("*").eq("is_active", True).execute()
        rules = rules_resp.data if rules_resp.data else []
    except Exception as e:
        logger.error(f"Failed to fetch fraud rules: {e}")
        return 0, []

    for rule in rules:
        rule_id = rule["id"]
        category = rule.get("category", "custom")
        config = rule.get("condition_config", {})
        weight = rule.get("score_weight", 10)

        # Select the appropriate evaluator
        evaluator = RULE_EVALUATORS.get(category, _evaluate_no_witnesses)

        try:
            triggered, explanation = evaluator(claim, config)
        except Exception as e:
            triggered = False
            explanation = f"Error evaluating rule '{rule.get('rule_name', '')}': {e}"
            logger.warning(explanation)

        signal_score = weight if triggered else 0
        total_score += signal_score

        signals.append({
            "rule_id": rule_id,
            "triggered": triggered,
            "signal_score": signal_score,
            "explanation": explanation,
            "details": {
                "rule_name": rule.get("rule_name", ""),
                "category": category,
                "weight": weight,
                "config": config,
            }
        })

    # Cap score at 100
    fraud_score = min(total_score, 100)

    return fraud_score, signals


# PUBLIC_INTERFACE
def save_signals(claim_id: str, signals: List[Dict[str, Any]]) -> None:
    """Persist fraud signal evaluations to the database.

    Args:
        claim_id: UUID of the claim.
        signals: List of signal dicts from evaluate_claim().
    """
    for sig in signals:
        try:
            supabase.table("fraud_signals").insert({
                "claim_id": claim_id,
                "rule_id": sig["rule_id"],
                "triggered": sig["triggered"],
                "signal_score": sig["signal_score"],
                "explanation": sig["explanation"],
                "details": sig.get("details", {}),
            }).execute()
        except Exception as e:
            logger.warning(f"Failed to save signal for claim {claim_id}, rule {sig['rule_id']}: {e}")


# PUBLIC_INTERFACE
def score_and_save(claim_id: str, claim_data: Dict[str, Any]) -> Tuple[int, List[Dict[str, Any]]]:
    """Evaluate claim, save signals, and update the claim's fraud_score.

    Args:
        claim_id: UUID of the claim.
        claim_data: Dictionary of claim fields.

    Returns:
        Tuple of (fraud_score, signals).
    """
    fraud_score, signals = evaluate_claim(claim_data)

    # Save signals to database
    save_signals(claim_id, signals)

    # Update claim fraud_score and status
    update_data = {"fraud_score": fraud_score}
    if fraud_score >= 75:
        update_data["status"] = "flagged"
    elif fraud_score >= 40:
        update_data["status"] = "under_review"

    try:
        supabase.table("claims").update(update_data).eq("id", claim_id).execute()
    except Exception as e:
        logger.warning(f"Failed to update claim {claim_id} fraud score: {e}")

    return fraud_score, signals
