"""
Main FastAPI application for the Insurance Fraud Detection Platform.

Provides REST API for:
- Claim ingestion (CSV upload and manual entry)
- Fraud scoring engine with 5+ configurable rules and explanations
- Investigator queues and assignment management
- Network/relationship visualization
- Fraud outcome logging
- Manager reporting with filters
- Fraud rules CRUD

CORS is configured from environment variables for frontend integration.
"""
import logging
import os

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# OpenAPI metadata and tags
openapi_tags = [
    {
        "name": "Health",
        "description": "Health check endpoint.",
    },
    {
        "name": "Claims",
        "description": "Claim ingestion (CSV and manual), retrieval, update, and fraud scoring.",
    },
    {
        "name": "Fraud Rules",
        "description": "CRUD operations for configurable fraud detection rules.",
    },
    {
        "name": "Assignments & Queues",
        "description": "Investigator assignment management and work queue operations.",
    },
    {
        "name": "Outcomes",
        "description": "Fraud investigation outcome logging and retrieval.",
    },
    {
        "name": "Network View",
        "description": "Network/relationship graph endpoints for entity visualization.",
    },
    {
        "name": "Reporting",
        "description": "Dashboard summaries and filtered report generation.",
    },
    {
        "name": "Users",
        "description": "User and investigator management endpoints.",
    },
]

app = FastAPI(
    title="Insurance Fraud Detection Platform API",
    description=(
        "Backend API for insurance SIU investigators and claims managers. "
        "Supports claim ingestion, configurable fraud scoring with explanations, "
        "investigator queues, network visualization, outcome logging, and reporting."
    ),
    version="1.0.0",
    openapi_tags=openapi_tags,
)

# ---- CORS Configuration from environment ----
allowed_origins_str = os.getenv("ALLOWED_ORIGINS", "*")
allowed_origins = [o.strip() for o in allowed_origins_str.split(",") if o.strip()]

# Also include FRONTEND_URL if set, to ensure the frontend origin is always allowed
frontend_url = os.getenv("FRONTEND_URL", "")
if frontend_url and frontend_url not in allowed_origins:
    allowed_origins.append(frontend_url)

if not allowed_origins:
    allowed_origins = ["*"]

allowed_methods_str = os.getenv("ALLOWED_METHODS", "GET,POST,PUT,DELETE,PATCH,OPTIONS")
allowed_methods = [m.strip() for m in allowed_methods_str.split(",") if m.strip()]

# Ensure commonly needed headers are always included
allowed_headers_str = os.getenv(
    "ALLOWED_HEADERS",
    "Content-Type,Authorization,X-Requested-With,Accept,Origin"
)
allowed_headers = [h.strip() for h in allowed_headers_str.split(",") if h.strip()]
# Add Accept and Origin if not already present (browsers send these automatically)
for required_header in ["Accept", "Origin"]:
    if required_header not in allowed_headers:
        allowed_headers.append(required_header)

cors_max_age = int(os.getenv("CORS_MAX_AGE", "3600"))

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=allowed_methods,
    allow_headers=allowed_headers,
    max_age=cors_max_age,
)

# ---- Import and register route modules ----
from src.api.routes_claims import router as claims_router
from src.api.routes_rules import router as rules_router
from src.api.routes_assignments import router as assignments_router
from src.api.routes_outcomes import router as outcomes_router
from src.api.routes_network import router as network_router
from src.api.routes_reports import router as reports_router
from src.api.routes_users import router as users_router

app.include_router(claims_router)
app.include_router(rules_router)
app.include_router(assignments_router)
app.include_router(outcomes_router)
app.include_router(network_router)
app.include_router(reports_router)
app.include_router(users_router)


# ---- Health check ----

# PUBLIC_INTERFACE
@app.get("/", tags=["Health"], summary="Health Check", description="Returns application health status.")
def health_check():
    """Health check endpoint.

    Returns:
        dict: Health status message.
    """
    return {"status": "healthy", "service": "Insurance Fraud Detection Platform API"}


# PUBLIC_INTERFACE
@app.get(
    "/api/health",
    tags=["Health"],
    summary="API Health Check",
    description="Returns API health status with database connectivity info.",
)
def api_health():
    """API health check with database connectivity status.

    Returns:
        dict: Health status with database connection information.
    """
    db_status = "unknown"
    try:
        from src.api.database import supabase as db_client
        if db_client:
            # Try a simple query to verify connectivity
            db_client.table("users").select("id").limit(1).execute()
            db_status = "connected"
        else:
            db_status = "not_configured"
    except Exception as e:
        db_status = f"error: {str(e)}"

    return {
        "status": "healthy",
        "service": "Insurance Fraud Detection Platform API",
        "database": db_status,
    }


logger.info("Insurance Fraud Detection Platform API initialized successfully.")
