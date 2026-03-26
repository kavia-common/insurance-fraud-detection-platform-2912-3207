# Supabase Integration - Insurance Fraud Detection Platform

## Overview
The backend API connects to Supabase as its primary PostgreSQL database using the Supabase Python client library (`supabase>=2.0.0`).
The frontend dashboard communicates with Supabase **indirectly** through the backend API (via Next.js rewrites to port 3001).

## Environment Variables

### Backend API (`backend_api`)
- `SUPABASE_URL`: The Supabase project URL
- `SUPABASE_KEY`: The Supabase anon/public API key

### Frontend Dashboard (`frontend_dashboard`)
- `NEXT_PUBLIC_SUPABASE_URL`: The Supabase project URL (available but frontend uses backend proxy)
- `NEXT_PUBLIC_SUPABASE_KEY`: The Supabase anon/public API key (available but frontend uses backend proxy)
- `NEXT_PUBLIC_API_BASE`: Backend API base URL for proxied requests
- `NEXT_PUBLIC_BACKEND_URL`: Backend service URL

> **Note:** The frontend does NOT use a direct Supabase client. All data flows through the backend API.

## Connection
The Supabase client is initialized in `backend_api/src/api/database.py` using:
```python
from supabase import create_client, Client
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
```
All database operations use the Supabase REST API through the Python client.

## Database Schema

### Tables (12 total)

| Table | Description |
|-------|-------------|
| `users` | System users (investigators, managers, admins) with role enum |
| `policyholders` | Insurance policyholders with PII |
| `policies` | Insurance policies linked to policyholders |
| `claims` | Insurance claims with fraud scores, computed risk_level. Includes claimant_name, claimant_address, policy_number (text), and third_parties (text) fields for AC1 ingestion. |
| `fraud_rules` | Configurable fraud detection rules (6 default rules) |
| `fraud_signals` | Per-claim rule evaluation results with explanations |
| `investigator_assignments` | Claim-to-investigator assignments with status tracking |
| `claim_outcomes` | Fraud investigation outcomes with recovery amounts |
| `network_relationships` | Entity relationship graph data for network views |
| `claim_documents` | Claim document attachments |
| `audit_log` | Compliance audit trail |
| `report_snapshots` | Saved report data for manager reporting |

### Custom Enums
- `claim_status`: new, under_review, flagged, investigating, closed_confirmed_fraud, closed_legitimate, closed_insufficient_evidence
- `assignment_status`: pending, accepted, in_progress, completed, reassigned
- `fraud_outcome_type`: confirmed_fraud, legitimate, insufficient_evidence, referred_to_law_enforcement, pending
- `user_role`: investigator, manager, admin
- `rule_category`: amount, frequency, timing, location, pattern, network, custom

### New Claims Columns (AC1 Ingestion Fields)
The `claims` table includes the following additional text columns for claim ingestion:
- `claimant_name` (TEXT, nullable): Full name of the claimant filing the claim
- `claimant_address` (TEXT, nullable): Mailing or residential address of the claimant
- `policy_number` (TEXT, nullable): Human-readable policy number associated with the claim
- `third_parties` (TEXT, nullable): Comma-separated list or free-text of third-party names/entities involved in the claim

**Migration SQL for adding these columns (if not already present):**
```sql
ALTER TABLE claims ADD COLUMN IF NOT EXISTS claimant_name TEXT;
ALTER TABLE claims ADD COLUMN IF NOT EXISTS claimant_address TEXT;
ALTER TABLE claims ADD COLUMN IF NOT EXISTS policy_number TEXT;
ALTER TABLE claims ADD COLUMN IF NOT EXISTS third_parties TEXT;
```

### Computed Columns
- `claims.risk_level`: Generated ALWAYS AS based on fraud_score (high ≥75, medium ≥40, low <40)

### Indexes (18 total)
Performance indexes on all frequently queried columns including:
- claims: status, fraud_score, policy_id, policyholder_id, assigned_investigator_id, filed_date
- fraud_signals: claim_id, rule_id
- investigator_assignments: investigator_id, claim_id, status
- claim_outcomes: claim_id
- network_relationships: entity_a, entity_b
- audit_log: entity, user_id
- policies: policyholder_id
- claim_documents: claim_id

### Triggers
- `update_updated_at_column()`: Auto-updates `updated_at` on UPDATE for users, policyholders, policies, claims, fraud_rules, investigator_assignments, claim_outcomes

## RLS Policies
Row Level Security is enabled on **all 12 tables**. Current policies allow anon access for all operations
(the backend handles application-level authorization via the anon key).

Each table has a policy: `anon_all_<table>` granting full CRUD to the `anon` role.

## Seed Data

### Default Users (3)
| ID | Email | Role | Department |
|----|-------|------|------------|
| `00000000-...-000000000001` | admin@insure.com | admin | Admin |
| `00000000-...-000000000002` | mgr@insure.com | manager | SIU |
| `00000000-...-000000000003` | inv@insure.com | investigator | SIU |

### Default Fraud Rules (11)
| Rule Name | Category | Weight | Evaluator Key | Description |
|-----------|----------|--------|---------------|-------------|
| High Amount | amount | 25 | high_amount | Flags claims over $15,000 |
| Quick Filing | timing | 18 | quick_filing | Filed within 2 days of incident |
| Recent Address Change | pattern | 15 | no_police_report | Address changed <3m before claim |
| Multiple Claims in 6 Months | frequency | 20 | frequency | >2 claims in 6m from same holder |
| Out-of-State Incident | location | 10 | location | Incident state ≠ policyholder state |
| Known Fraud Network | network | 30 | network | Related to prior fraud network |
| Duplicate Claimant | pattern | 20 | duplicate_claimant | Same claimant name on multiple claims |
| Suspicious Description | custom | 15 | suspicious_description | Description contains fraud-indicator keywords |
| Third Party Involvement | custom | 12 | third_party_involvement | Claims involving third parties |
| Recent Policy | timing | 18 | recent_policy | Incident within 30 days of policy start |
| Address Reuse | pattern | 15 | address_match | Same claimant address on 2+ claims |

### Available Evaluator Keys (12)
Rules can specify an `evaluator` key in their `condition_config` JSON to use a specific evaluator function:
| Evaluator Key | Description |
|---------------|-------------|
| `high_amount` | Flag claims exceeding a dollar-amount threshold |
| `quick_filing` | Flag claims filed suspiciously soon after incident |
| `frequency` | Flag policyholders with multiple claims in a time window |
| `no_police_report` | Flag high-value claims without a police report |
| `no_witnesses` | Flag high-value claims with zero witnesses |
| `location` | Flag claims with suspicious location keywords |
| `network` | Flag policyholders linked to known fraud networks |
| `duplicate_claimant` | Flag claimant names appearing on multiple claims |
| `suspicious_description` | Flag descriptions containing suspicious keywords |
| `third_party_involvement` | Flag claims involving third parties |
| `recent_policy` | Flag claims filed shortly after policy inception |
| `address_match` | Flag claimant addresses reused across multiple claims |

### Sample Data
- 1 policyholder (Elena Smith)
- 1 policy (POL123456, Auto)
- 1 claim (CLM5555, Collision, $16,000, fraud_score=82, risk_level=high)
- 3 fraud signals for the sample claim
- 1 investigator assignment
- 1 claim outcome (confirmed_fraud, $13,000 recovery)
- 1 network relationship

## Schema Management
The database schema is managed via the `claims_database` container:
- `claims_database/scripts/migrate.py` - Full DDL migration
- `claims_database/scripts/seed_data.py` - Seed data population

## Dependencies
### Backend (Python)
- `supabase>=2.0.0` - Supabase Python client
- `python-dotenv==1.1.0` - Environment variable loading

### Frontend (Node.js)
- No direct Supabase dependency needed (uses backend API proxy)

## Setup Instructions

### IMPORTANT: Supabase Configuration
1. Ensure `SUPABASE_URL` and `SUPABASE_KEY` environment variables are set for the backend
2. Ensure `NEXT_PUBLIC_SUPABASE_URL` and `NEXT_PUBLIC_SUPABASE_KEY` are set for the frontend container
3. Run migration script or use SupabaseTools to create schema
4. Run seed script or use SupabaseTools to populate default data
5. Verify tables exist and seed data is present via Supabase dashboard
