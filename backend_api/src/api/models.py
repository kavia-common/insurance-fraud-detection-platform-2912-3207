"""
Pydantic models for the Insurance Fraud Detection Platform API.
Defines request/response schemas for claims, rules, assignments, outcomes, and reporting.
"""
from datetime import date
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field
from enum import Enum


# ---- Enums ----

class ClaimStatus(str, Enum):
    """Possible statuses for a claim."""
    NEW = "new"
    UNDER_REVIEW = "under_review"
    FLAGGED = "flagged"
    INVESTIGATING = "investigating"
    CLOSED_CONFIRMED_FRAUD = "closed_confirmed_fraud"
    CLOSED_LEGITIMATE = "closed_legitimate"
    CLOSED_INSUFFICIENT_EVIDENCE = "closed_insufficient_evidence"


class AssignmentStatus(str, Enum):
    """Possible statuses for an investigator assignment."""
    PENDING = "pending"
    ACCEPTED = "accepted"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    REASSIGNED = "reassigned"


class FraudOutcomeType(str, Enum):
    """Possible fraud outcome types."""
    CONFIRMED_FRAUD = "confirmed_fraud"
    LEGITIMATE = "legitimate"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"
    REFERRED_TO_LAW_ENFORCEMENT = "referred_to_law_enforcement"
    PENDING = "pending"


class UserRole(str, Enum):
    """User roles in the system."""
    INVESTIGATOR = "investigator"
    MANAGER = "manager"
    ADMIN = "admin"


class RuleCategory(str, Enum):
    """Categories for fraud detection rules."""
    AMOUNT = "amount"
    FREQUENCY = "frequency"
    TIMING = "timing"
    LOCATION = "location"
    PATTERN = "pattern"
    NETWORK = "network"
    CUSTOM = "custom"


# ---- Claim Models ----

# PUBLIC_INTERFACE
class ClaimCreate(BaseModel):
    """Schema for creating a new claim manually."""
    claim_number: str = Field(..., description="Unique claim reference number")
    policy_id: Optional[str] = Field(None, description="UUID of the associated policy")
    policyholder_id: Optional[str] = Field(None, description="UUID of the policyholder")
    claim_type: str = Field(..., description="Type of claim (e.g., Collision, Theft)")
    claim_amount: float = Field(..., description="Dollar amount of the claim", ge=0)
    incident_date: date = Field(..., description="Date the incident occurred")
    filed_date: Optional[date] = Field(None, description="Date claim was filed")
    description: Optional[str] = Field(None, description="Description of the claim")
    location: Optional[str] = Field(None, description="Location of the incident")
    police_report_filed: Optional[bool] = Field(False, description="Whether a police report was filed")
    police_report_number: Optional[str] = Field(None, description="Police report reference number")
    witnesses: Optional[int] = Field(0, description="Number of witnesses", ge=0)


# PUBLIC_INTERFACE
class ClaimResponse(BaseModel):
    """Schema for claim data returned from the API."""
    id: str = Field(..., description="UUID of the claim")
    claim_number: str = Field(..., description="Unique claim reference number")
    policy_id: Optional[str] = Field(None, description="Associated policy UUID")
    policyholder_id: Optional[str] = Field(None, description="Policyholder UUID")
    claim_type: str = Field(..., description="Type of claim")
    claim_amount: float = Field(..., description="Dollar amount")
    incident_date: str = Field(..., description="Incident date")
    filed_date: Optional[str] = Field(None, description="Filing date")
    description: Optional[str] = Field(None, description="Description")
    status: str = Field("new", description="Claim status")
    fraud_score: Optional[int] = Field(0, description="Computed fraud score 0-100")
    risk_level: Optional[str] = Field(None, description="Derived risk level: low/medium/high")
    location: Optional[str] = Field(None, description="Incident location")
    police_report_filed: Optional[bool] = Field(False, description="Police report filed flag")
    police_report_number: Optional[str] = Field(None, description="Police report number")
    witnesses: Optional[int] = Field(0, description="Number of witnesses")
    assigned_investigator_id: Optional[str] = Field(None, description="Assigned investigator UUID")
    ingestion_source: Optional[str] = Field("manual", description="How claim was ingested")
    created_at: Optional[str] = Field(None, description="Creation timestamp")
    updated_at: Optional[str] = Field(None, description="Last update timestamp")


class ClaimUpdate(BaseModel):
    """Schema for updating a claim."""
    claim_type: Optional[str] = None
    claim_amount: Optional[float] = None
    description: Optional[str] = None
    status: Optional[str] = None
    location: Optional[str] = None
    police_report_filed: Optional[bool] = None
    police_report_number: Optional[str] = None
    witnesses: Optional[int] = None


# ---- Fraud Rule Models ----

# PUBLIC_INTERFACE
class FraudRuleCreate(BaseModel):
    """Schema for creating a new fraud detection rule."""
    rule_name: str = Field(..., description="Unique name for the rule")
    description: str = Field(..., description="Human-readable description")
    category: RuleCategory = Field(RuleCategory.CUSTOM, description="Rule category")
    condition_config: Dict[str, Any] = Field(default_factory=dict, description="JSON config for rule conditions")
    score_weight: int = Field(10, description="Score weight 0-100", ge=0, le=100)
    is_active: bool = Field(True, description="Whether rule is active")


# PUBLIC_INTERFACE
class FraudRuleResponse(BaseModel):
    """Schema for fraud rule response."""
    id: str = Field(..., description="UUID of the rule")
    rule_name: str = Field(..., description="Rule name")
    description: str = Field(..., description="Rule description")
    category: str = Field(..., description="Rule category")
    condition_config: Dict[str, Any] = Field(default_factory=dict, description="Rule condition config")
    score_weight: int = Field(..., description="Score weight")
    is_active: bool = Field(True, description="Active flag")
    created_by: Optional[str] = Field(None, description="Creator UUID")
    created_at: Optional[str] = Field(None, description="Created timestamp")
    updated_at: Optional[str] = Field(None, description="Updated timestamp")


class FraudRuleUpdate(BaseModel):
    """Schema for updating a fraud rule."""
    rule_name: Optional[str] = None
    description: Optional[str] = None
    category: Optional[RuleCategory] = None
    condition_config: Optional[Dict[str, Any]] = None
    score_weight: Optional[int] = Field(None, ge=0, le=100)
    is_active: Optional[bool] = None


# ---- Fraud Signal Models ----

# PUBLIC_INTERFACE
class FraudSignalResponse(BaseModel):
    """Schema for a fraud signal (per-claim rule evaluation result)."""
    id: str = Field(..., description="Signal UUID")
    claim_id: str = Field(..., description="Claim UUID")
    rule_id: str = Field(..., description="Rule UUID")
    triggered: bool = Field(..., description="Whether the rule was triggered")
    signal_score: int = Field(..., description="Score contributed by this signal")
    explanation: Optional[str] = Field(None, description="Human-readable explanation")
    details: Optional[Dict[str, Any]] = Field(None, description="Extra details")
    evaluated_at: Optional[str] = Field(None, description="Evaluation timestamp")


# ---- Assignment Models ----

# PUBLIC_INTERFACE
class AssignmentCreate(BaseModel):
    """Schema for creating an investigator assignment."""
    claim_id: str = Field(..., description="UUID of the claim to assign")
    investigator_id: str = Field(..., description="UUID of the investigator")
    assigned_by: Optional[str] = Field(None, description="UUID of the assigning manager")
    priority: int = Field(5, description="Priority 1-10", ge=1, le=10)
    notes: Optional[str] = Field(None, description="Assignment notes")


# PUBLIC_INTERFACE
class AssignmentResponse(BaseModel):
    """Schema for assignment response."""
    id: str = Field(..., description="Assignment UUID")
    claim_id: str = Field(..., description="Claim UUID")
    investigator_id: str = Field(..., description="Investigator UUID")
    assigned_by: Optional[str] = Field(None, description="Assigned by UUID")
    status: str = Field(..., description="Assignment status")
    priority: int = Field(..., description="Priority level")
    notes: Optional[str] = Field(None, description="Notes")
    assigned_at: Optional[str] = Field(None, description="Assigned timestamp")
    accepted_at: Optional[str] = Field(None, description="Accepted timestamp")
    completed_at: Optional[str] = Field(None, description="Completed timestamp")
    updated_at: Optional[str] = Field(None, description="Updated timestamp")


class AssignmentUpdate(BaseModel):
    """Schema for updating an assignment."""
    status: Optional[str] = None
    priority: Optional[int] = Field(None, ge=1, le=10)
    notes: Optional[str] = None


# ---- Outcome Models ----

# PUBLIC_INTERFACE
class OutcomeCreate(BaseModel):
    """Schema for logging a fraud investigation outcome."""
    claim_id: str = Field(..., description="UUID of the claim")
    investigator_id: str = Field(..., description="UUID of the investigator")
    outcome: FraudOutcomeType = Field(..., description="Investigation outcome type")
    recovery_amount: Optional[float] = Field(0, description="Recovered amount", ge=0)
    summary: Optional[str] = Field(None, description="Summary of findings")
    evidence_notes: Optional[str] = Field(None, description="Evidence notes")
    resolution_date: Optional[date] = Field(None, description="Date of resolution")


# PUBLIC_INTERFACE
class OutcomeResponse(BaseModel):
    """Schema for outcome response."""
    id: str = Field(..., description="Outcome UUID")
    claim_id: str = Field(..., description="Claim UUID")
    investigator_id: str = Field(..., description="Investigator UUID")
    outcome: str = Field(..., description="Outcome type")
    recovery_amount: Optional[float] = Field(0, description="Recovered amount")
    summary: Optional[str] = Field(None, description="Summary")
    evidence_notes: Optional[str] = Field(None, description="Evidence notes")
    resolution_date: Optional[str] = Field(None, description="Resolution date")
    created_at: Optional[str] = Field(None, description="Created timestamp")
    updated_at: Optional[str] = Field(None, description="Updated timestamp")


class OutcomeUpdate(BaseModel):
    """Schema for updating an outcome."""
    outcome: Optional[FraudOutcomeType] = None
    recovery_amount: Optional[float] = Field(None, ge=0)
    summary: Optional[str] = None
    evidence_notes: Optional[str] = None
    resolution_date: Optional[date] = None


# ---- Network Models ----

# PUBLIC_INTERFACE
class NetworkNodeResponse(BaseModel):
    """Schema for a node in the network graph."""
    id: str = Field(..., description="Entity UUID")
    type: str = Field(..., description="Entity type (policyholder, claim, etc.)")
    label: str = Field(..., description="Display label")
    metadata: Optional[Dict[str, Any]] = Field(None, description="Additional node data")


# PUBLIC_INTERFACE
class NetworkEdgeResponse(BaseModel):
    """Schema for an edge/relationship in the network graph."""
    id: str = Field(..., description="Relationship UUID")
    source: str = Field(..., description="Source entity UUID")
    target: str = Field(..., description="Target entity UUID")
    source_type: str = Field(..., description="Source entity type")
    target_type: str = Field(..., description="Target entity type")
    relationship_type: str = Field(..., description="Type of relationship")
    strength: Optional[float] = Field(1.0, description="Relationship strength")


# PUBLIC_INTERFACE
class NetworkGraphResponse(BaseModel):
    """Full network graph response with nodes and edges."""
    nodes: List[NetworkNodeResponse] = Field(default_factory=list, description="Graph nodes")
    edges: List[NetworkEdgeResponse] = Field(default_factory=list, description="Graph edges")


# ---- User Models ----

# PUBLIC_INTERFACE
class UserResponse(BaseModel):
    """Schema for user data."""
    id: str = Field(..., description="User UUID")
    email: str = Field(..., description="User email")
    full_name: str = Field(..., description="Full name")
    role: str = Field(..., description="User role")
    department: Optional[str] = Field(None, description="Department")
    is_active: bool = Field(True, description="Active flag")
    max_caseload: Optional[int] = Field(20, description="Maximum caseload")
    current_caseload: Optional[int] = Field(0, description="Current caseload")
    created_at: Optional[str] = Field(None, description="Created timestamp")


# ---- Reporting Models ----

# PUBLIC_INTERFACE
class ReportFilters(BaseModel):
    """Filters for generating reports."""
    start_date: Optional[str] = Field(None, description="Start date (YYYY-MM-DD)")
    end_date: Optional[str] = Field(None, description="End date (YYYY-MM-DD)")
    status: Optional[str] = Field(None, description="Filter by claim status")
    risk_level: Optional[str] = Field(None, description="Filter by risk level: low/medium/high")
    investigator_id: Optional[str] = Field(None, description="Filter by investigator UUID")
    claim_type: Optional[str] = Field(None, description="Filter by claim type")


# PUBLIC_INTERFACE
class DashboardSummary(BaseModel):
    """Dashboard summary statistics."""
    total_claims: int = Field(0, description="Total number of claims")
    flagged_claims: int = Field(0, description="Number of flagged claims")
    high_risk_claims: int = Field(0, description="Claims with high risk score")
    under_investigation: int = Field(0, description="Claims currently being investigated")
    confirmed_fraud: int = Field(0, description="Confirmed fraud outcomes")
    total_recovery: float = Field(0, description="Total recovery amount")
    avg_fraud_score: float = Field(0, description="Average fraud score across claims")
    claims_by_status: Dict[str, int] = Field(default_factory=dict, description="Claim counts per status")
    claims_by_risk: Dict[str, int] = Field(default_factory=dict, description="Claim counts per risk level")


# PUBLIC_INTERFACE
class ReportResponse(BaseModel):
    """Report data response."""
    id: Optional[str] = Field(None, description="Report UUID")
    report_type: str = Field(..., description="Type of report")
    filters: Optional[Dict[str, Any]] = Field(None, description="Applied filters")
    data: Dict[str, Any] = Field(default_factory=dict, description="Report data")
    generated_at: Optional[str] = Field(None, description="Generation timestamp")


# ---- CSV Upload ----

# PUBLIC_INTERFACE
class CSVUploadResponse(BaseModel):
    """Response after CSV claim ingestion."""
    total_rows: int = Field(..., description="Total rows in CSV")
    successfully_ingested: int = Field(..., description="Successfully ingested rows")
    failed_rows: int = Field(..., description="Failed rows")
    errors: List[Dict[str, Any]] = Field(default_factory=list, description="Error details per failed row")
    claim_ids: List[str] = Field(default_factory=list, description="Created claim UUIDs")
