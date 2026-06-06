"""Supabase client for FitForge (multi-user).

The server holds the service-role key and is the only thing that talks to the
database. Every query in app.py is scoped by the logged-in user's id (from the
Flask session), so users only ever touch their own rows. Credential hashes in
the users table are never sent to the browser.
"""
import os
from supabase import create_client, Client

_client: Client | None = None


def db() -> Client:
    """Return a cached service-role Supabase client."""
    global _client
    if _client is None:
        url = os.environ.get("SUPABASE_URL", "")
        key = os.environ.get("SUPABASE_SERVICE_KEY", "")
        _client = create_client(url, key)
    return _client
