"""
Supabase client module for the Insurance Fraud Detection Platform.
Provides a singleton Supabase client configured via environment variables.
"""
import os
from dotenv import load_dotenv
from supabase import create_client, Client

# Load environment variables from .env file
load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "")


# PUBLIC_INTERFACE
def get_supabase_client() -> Client:
    """Return a configured Supabase client instance.

    Uses SUPABASE_URL and SUPABASE_KEY environment variables.

    Returns:
        Client: An authenticated Supabase client.

    Raises:
        ValueError: If SUPABASE_URL or SUPABASE_KEY is not set.
    """
    if not SUPABASE_URL or not SUPABASE_KEY:
        raise ValueError(
            "SUPABASE_URL and SUPABASE_KEY environment variables must be set."
        )
    return create_client(SUPABASE_URL, SUPABASE_KEY)


# Create a module-level client for reuse
supabase: Client = get_supabase_client() if SUPABASE_URL and SUPABASE_KEY else None  # type: ignore
