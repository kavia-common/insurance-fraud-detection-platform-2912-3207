# Supabase Integration - Backend API

## Overview
The backend API connects to Supabase as its primary database using the Supabase Python client library.

## Environment Variables
- `SUPABASE_URL`: The Supabase project URL (e.g., `https://project-ref.supabase.co`)
- `SUPABASE_KEY`: The Supabase anon/public API key

## Connection
The Supabase client is initialized in `src/api/database.py` using `create_client(SUPABASE_URL, SUPABASE_KEY)`.
All database operations use the Supabase REST API through the Python client.

## Tables Used
The backend interacts with the following tables:
- `users` - System users (investigators, managers, admins)
- `policyholders` - Insurance policyholders
- `policies` - Insurance policies
- `claims` - Insurance claims with fraud scores
- `fraud_rules` - Configurable fraud detection rules
- `fraud_signals` - Per-claim rule evaluation results
- `investigator_assignments` - Claim-to-investigator assignments
- `claim_outcomes` - Fraud investigation outcomes
- `network_relationships` - Entity relationship graph data
- `claim_documents` - Claim document attachments
- `audit_log` - Compliance audit trail
- `report_snapshots` - Saved report data

## RLS Policies
Row Level Security is enabled on all tables. Current policies allow anon access for all operations
(the backend handles application-level authorization).

## Schema
The database schema is managed via the `claims_database` container's migration scripts.
See `claims_database/scripts/migrate.py` for the full DDL.
