#!/usr/bin/env python3
"""Helper script to write the updated fraud_engine.py file."""
import os

TARGET = os.path.join(os.path.dirname(__file__), "src", "api", "fraud_engine.py")

CONTENT = '''\
"""
Fraud Scoring Engine for the Insurance Fraud Detection Platform.
Evaluates claims against configurable fraud detection rules and generates
fraud scores (0-100) with human-readable explanations.

Supports 12 built-in rule evaluators covering amount, timing, frequency,
pattern, location, network, and custom categories.  Rules are dispatched
by an explicit evaluator key in their condition_config JSON first,
then by rule_name fuzzy match, and finally by category fallback.
"""
from datetime import datetime
from typing import Any, Callable, Dict, List, Tuple
import logging
import re

from src.api.database import supabase

logger = logging.getLogger(__name__)


# ---- Built-in rule evaluators ----

# PUBLIC_INTERFACE
def _evaluate_high_amount(claim: Dict[str, Any], config: Dict[str, Any]) -> Tuple[bool, str]:
    """Check if claim amount exceeds a configurable threshold."""
    threshold = float(config.get("threshold", 15000))
    amount = float(claim.get("claim_amount", 0))
    if amount > threshold:
        return True, f"Claim amount ${amount:,.2f} exceeds threshold ${threshold:,.2f}"
    return False, f"Claim amount ${amount:,.2f} is within threshold ${threshold:,.2f}"


# PUBLIC_INTERFACE
def _evaluate_quick_filing(claim: Dict[str, Any], config: Dict[str, Any]) -> Tuple[bool, str]:
    """Check if claim was filed suspiciously soon after the incident."""
    days_threshold = int(config.get("days", 2))
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


# PUBLIC_INTERFACE
def _evaluate_frequency(claim: Dict[str, Any], config: Dict[str, Any]) -> Tuple[bool, str]:
    """Check if policyholder has multiple claims within a time window."""
    months = int(config.get("months", 6))
    count_threshold = int(config.get("count", 2))
    policyholder_id = claim.get("policyholder_id")
    if not policyholder_id:
        return False, "No policyholder linked; cannot check frequency"
    try:
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


# PUBLIC_INTERFACE
def _evaluate_no_police_report(claim: Dict[str, Any], config: Dict[str, Any]) -> Tuple[bool, str]:
    """Flag claims above a dollar amount that lack a police report."""
    threshold = float(config.get("threshold", 5000))
    amount = float(claim.get("claim_amount", 0))
    has_report = claim.get("police_report_filed", False)
    if amount > threshold and not has_report:
        return True, f"No police report for ${amount:,.2f} claim (threshold: ${threshold:,.2f})"
    return False, "Police report filed or amount below threshold"


# PUBLIC_INTERFACE
def _evaluate_no_witnesses(claim: Dict[str, Any], config: Dict[str, Any]) -> Tuple[bool, str]:
    """Flag high-value claims with zero witnesses."""
    threshold = float(config.get("threshold", 10000))
    amount = float(claim.get("claim_amount", 0))
    witnesses = int(claim.get("witnesses", 0) or 0)
    if amount > threshold and witnesses == 0:
        return True, f"No witnesses for ${amount:,.2f} claim (threshold: ${threshold:,.2f})"
    return False, "Witnesses present or amount below threshold"


# PUBLIC_INTERFACE
def _evaluate_location(claim: Dict[str, Any], config: Dict[str, Any]) -> Tuple[bool, str]:
    """Check for suspicious location patterns using keyword matching."""
    claim_location = claim.get("location", "")
    if not claim_location:
        return False, "No location data available for location check"
    suspicious_keywords = config.get("suspicious_keywords", [])
    for kw in suspicious_keywords:
        if kw.lower() in claim_location.lower():
            return True, f"Location \\'{claim_location}\\' matches suspicious keyword \\'{kw}\\'"
    return False, f"Location \\'{claim_location}\\' does not match suspicious patterns"


# PUBLIC_INTERFACE
def _evaluate_network(claim: Dict[str, Any], config: Dict[str, Any]) -> Tuple[bool, str]:
    """Check if claim policyholder is linked to a known fraud network."""
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


# ---- NEW evaluators (AC2 gap rules) ----

# PUBLIC_INTERFACE
def _evaluate_duplicate_claimant(claim: Dict[str, Any], config: Dict[str, Any]) -> Tuple[bool, str]:
    """Detect if the same claimant name appears on multiple recent claims."""
    count_threshold = int(config.get("count", 1))
    claimant_name = (claim.get("claimant_name") or "").strip()
    if not claimant_name:
        return False, "No claimant name provided; cannot check for duplicates"
    try:
        resp = supabase.table("claims").select("id").ilike(
            "claimant_name", claimant_name
        ).execute()
        claim_id = claim.get("id")
        matches = [r for r in (resp.data or []) if r.get("id") != claim_id]
        match_count = len(matches)
        if match_count >= count_threshold:
            return True, (
                f"Claimant \\'{claimant_name}\\' appears on {match_count} other claim(s) "
                f"(threshold: {count_threshold})"
            )
        return False, f"Claimant \\'{claimant_name}\\' has {match_count} other claim(s)"
    except Exception as e:
        logger.warning(f"Duplicate claimant check failed: {e}")
        return False, f"Duplicate claimant check error: {e}"


# PUBLIC_INTERFACE
def _evaluate_suspicious_description(claim: Dict[str, Any], config: Dict[str, Any]) -> Tuple[bool, str]:
    """Flag claims whose description contains suspicious keywords or phrases."""
    default_keywords = [
        "total loss", "arson", "staged", "phantom", "exaggerated",
        "inflated", "fabricated", "pre-existing damage", "not at scene",
        "no witnesses", "cash only", "untraceable",
    ]
    keywords = config.get("keywords", default_keywords)
    description = (claim.get("description") or "").lower()
    if not description:
        return False, "No description provided for keyword analysis"
    matched = [kw for kw in keywords if kw.lower() in description]
    if matched:
        return True, f"Description contains suspicious keyword(s): {\\', \\'.join(matched)}"
    return False, "Description does not contain suspicious keywords"


# PUBLIC_INTERFACE
def _evaluate_third_party_involvement(claim: Dict[str, Any], config: Dict[str, Any]) -> Tuple[bool, str]:
    """Flag claims that involve third parties, which can indicate organised fraud."""
    min_parties = int(config.get("min_parties", 1))
    third_parties_raw = (claim.get("third_parties") or "").strip()
    if not third_parties_raw:
        return False, "No third-party information provided"
    parties = [p.strip() for p in re.split(r"[,;\\\\n]+", third_parties_raw) if p.strip()]
    party_count = len(parties)
    if party_count >= min_parties:
        label = "party" if party_count == 1 else "parties"
        preview = ", ".join(parties[:5])
        suffix = "..." if party_count > 5 else ""
        return True, (
            f"Claim involves {party_count} third {label} "
            f"(threshold: {min_parties}): {preview}{suffix}"
        )
    return False, f"Third-party count ({party_count}) below threshold ({min_parties})"


# PUBLIC_INTERFACE
def _evaluate_recent_policy(claim: Dict[str, Any], config: Dict[str, Any]) -> Tuple[bool, str]:
    """Flag claims filed shortly after the policy start date."""
    days_threshold = int(config.get("days", 30))
    policy_id = claim.get("policy_id")
    if not policy_id:
        return False, "No policy linked; cannot check policy age"
    try:
        policy_resp = supabase.table("policies").select("start_date").eq(
            "id", policy_id
        ).execute()
        if not policy_resp.data:
            return False, "Policy not found; cannot check policy age"
        start_str = policy_resp.data[0].get("start_date")
        if not start_str:
            return False, "Policy has no start_date; cannot check policy age"
        policy_start = datetime.strptime(str(start_str)[:10], "%Y-%m-%d").date()
        incident_str = claim.get("incident_date")
        if not incident_str:
            return False, "No incident date; cannot check policy age"
        incident_date = datetime.strptime(str(incident_str)[:10], "%Y-%m-%d").date()
        diff = (incident_date - policy_start).days
        if 0 <= diff <= days_threshold:
            return True, (
                f"Incident occurred {diff} day(s) after policy start "
                f"(threshold: {days_threshold} days)"
            )
        return False, (
            f"Incident {diff} day(s) after policy start "
            f"(threshold: {days_threshold} days)"
        )
    except Exception as e:
        logger.warning(f"Recent policy check failed: {e}")
        return False, f"Recent policy check error: {e}"


# PUBLIC_INTERFACE
def _evaluate_address_match(claim: Dict[str, Any], config: Dict[str, Any]) -> Tuple[bool, str]:
    """Detect if the same claimant address appears on multiple claims."""
    count_threshold = int(config.get("count", 2))
    address = (claim.get("claimant_address") or "").strip()
    if not address:
        return False, "No claimant address provided; cannot check for address reuse"
    try:
        resp = supabase.table("claims").select("id").ilike(
            "claimant_address", address
        ).execute()
        claim_id = claim.get("id")
        matches = [r for r in (resp.data or []) if r.get("id") != claim_id]
        match_count = len(matches)
        if match_count >= count_threshold:
            return True, (
                f"Address \\'{address}\\' appears on {match_count} other claim(s) "
                f"(threshold: {count_threshold})"
            )
        return False, f"Address used in {match_count} other claim(s)"
    except Exception as e:
        logger.warning(f"Address match check failed: {e}")
        return False, f"Address match check error: {e}"


# ---- Evaluator registries ----

CATEGORY_EVALUATORS: Dict[str, Callable] = {
    "amount": _evaluate_high_amount,
    "timing": _evaluate_quick_filing,
    "frequency": _evaluate_frequency,
    "pattern": _evaluate_no_police_report,
    "location": _evaluate_location,
    "network": _evaluate_network,
    "custom": _evaluate_no_witnesses,
}

NAMED_EVALUATORS: Dict[str, Callable] = {
    "high_amount": _evaluate_high_amount,
    "quick_filing": _evaluate_quick_filing,
    "frequency": _evaluate_frequency,
    "no_police_report": _evaluate_no_police_report,
    "no_witnesses": _evaluate_no_witnesses,
    "location": _evaluate_location,
    "network": _evaluate_network,
    "duplicate_claimant": _evaluate_duplicate_claimant,
    "suspicious_description": _evaluate_suspicious_description,
    "third_party_involvement": _evaluate_third_party_involvement,
    "recent_policy": _evaluate_recent_policy,
    "address_match": _evaluate_address_match,
}

RULE_EVALUATORS = CATEGORY_EVALUATORS


def _resolve_evaluator(rule: Dict[str, Any]) -> Callable:
    """Resolve the correct evaluator function for a given rule."""
    config = rule.get("condition_config") or {}
    category = rule.get("category", "custom")
    evaluator_key = config.get("evaluator")
    if evaluator_key and evaluator_key in NAMED_EVALUATORS:
        return NAMED_EVALUATORS[evaluator_key]
    rule_name = (rule.get("rule_name") or "").lower().replace(" ", "_").replace("-", "_")
    for key, func in NAMED_EVALUATORS.items():
        if key in rule_name or rule_name in key:
            return func
    if category in CATEGORY_EVALUATORS:
        return CATEGORY_EVALUATORS[category]
    return _evaluate_no_witnesses


# ---- Core scoring API ----

# PUBLIC_INTERFACE
def evaluate_claim(claim: Dict[str, Any]) -> Tuple[int, List[Dict[str, Any]]]:
    """Evaluate a claim against all active fraud rules and compute a fraud score."""
    signals: List[Dict[str, Any]] = []
    total_score = 0
    try:
        rules_resp = supabase.table("fraud_rules").select("*").eq("is_active", True).execute()
        rules = rules_resp.data if rules_resp.data else []
    except Exception as e:
        logger.error(f"Failed to fetch fraud rules: {e}")
        return 0, []
    for rule in rules:
        rule_id = rule["id"]
        category = rule.get("category", "custom")
        config = rule.get("condition_config") or {}
        weight = rule.get("score_weight", 10)
        evaluator = _resolve_evaluator(rule)
        try:
            triggered, explanation = evaluator(claim, config)
        except Exception as e:
            triggered = False
            explanation = f"Error evaluating rule \\'{rule.get(\\'rule_name\\', \\'\\')}\\':" + str(e)
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
            },
        })
    fraud_score = min(total_score, 100)
    return fraud_score, signals


# PUBLIC_INTERFACE
def save_signals(claim_id: str, signals: List[Dict[str, Any]]) -> None:
    """Persist fraud signal evaluations to the database."""
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
            logger.warning(f"Failed to save signal for claim {claim_id}, rule {sig[\\'rule_id\\']}: {e}")


# PUBLIC_INTERFACE
def score_and_save(claim_id: str, claim_data: Dict[str, Any]) -> Tuple[int, List[Dict[str, Any]]]:
    """Evaluate claim, save signals, and update the claim fraud_score."""
    fraud_score, signals = evaluate_claim(claim_data)
    save_signals(claim_id, signals)
    if fraud_score >= 75:
        risk_level = "high"
    elif fraud_score >= 40:
        risk_level = "medium"
    else:
        risk_level = "low"
    update_data: Dict[str, Any] = {"fraud_score": fraud_score, "risk_level": risk_level}
    if fraud_score >= 75:
        update_data["status"] = "flagged"
    elif fraud_score >= 40:
        update_data["status"] = "under_review"
    try:
        supabase.table("claims").update(update_data).eq("id", claim_id).execute()
    except Exception as e:
        logger.warning(f"Failed to update claim {claim_id} fraud score: {e}")
    return fraud_score, signals


# PUBLIC_INTERFACE
def get_available_evaluators() -> List[Dict[str, str]]:
    """Return all available named evaluator keys with descriptions."""
    descriptions = {
        "high_amount": "Flag claims exceeding a dollar-amount threshold",
        "quick_filing": "Flag claims filed suspiciously soon after incident",
        "frequency": "Flag policyholders with multiple claims in a time window",
        "no_police_report": "Flag high-value claims without a police report",
        "no_witnesses": "Flag high-value claims with zero witnesses",
        "location": "Flag claims with suspicious location keywords",
        "network": "Flag policyholders linked to known fraud networks",
        "duplicate_claimant": "Flag claimant names appearing on multiple claims",
        "suspicious_description": "Flag descriptions containing suspicious keywords",
        "third_party_involvement": "Flag claims involving third parties",
        "recent_policy": "Flag claims filed shortly after policy inception",
        "address_match": "Flag claimant addresses reused across multiple claims",
    }
    return [
        {"evaluator_key": key, "description": desc}
        for key, desc in descriptions.items()
    ]
'''

with open(TARGET, 'w') as f:
    f.write(CONTENT)

print(f"Written {len(CONTENT)} chars to {TARGET}")
