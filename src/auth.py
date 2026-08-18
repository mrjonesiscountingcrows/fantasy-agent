"""
src/auth.py
Yahoo OAuth2 — single source of truth for all authentication.

Replaces: yahoo_auth.py, get_access_token.py, get_refresh_token.py, setup_oauth.py

First-time setup (one-time only):
    python -m src.auth setup

Normal usage everywhere else:
    from src.auth import get_token
    token = get_token()
"""

from __future__ import annotations

import base64
import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional
from urllib.parse import urlencode

import requests
from dotenv import load_dotenv

load_dotenv()

# --- Config from .env ---
YAHOO_CLIENT_ID     = os.getenv("YAHOO_CLIENT_ID", "")
YAHOO_CLIENT_SECRET = os.getenv("YAHOO_CLIENT_SECRET", "")
YAHOO_REDIRECT_URI  = os.getenv("YAHOO_REDIRECT_URI", "oob")

# Token stored locally (gitignored via config/)
TOKEN_STORE = Path(os.getenv("YAHOO_TOKEN_PATH", "config/yahoo_token.json"))

# Yahoo endpoints
TOKEN_URL = "https://api.login.yahoo.com/oauth2/get_token"
AUTH_URL  = "https://api.login.yahoo.com/oauth2/request_auth"

# Refresh if token expires within this many seconds
EXPIRY_SKEW = 120


# ------------------------------------
# Data types
# ------------------------------------
@dataclass
class OAuthTokens:
    access_token: str
    refresh_token: Optional[str] = None
    token_type: str = "Bearer"
    expires_in: Optional[int] = None
    expires_at: Optional[int] = None


# ------------------------------------
# Internal helpers
# ------------------------------------
def _now() -> int:
    return int(time.time())


def _check_env() -> None:
    missing = [k for k, v in {
        "YAHOO_CLIENT_ID": YAHOO_CLIENT_ID,
        "YAHOO_CLIENT_SECRET": YAHOO_CLIENT_SECRET,
    }.items() if not v]
    if missing:
        raise RuntimeError(
            f"Missing env vars: {', '.join(missing)}. "
            "Add them to your .env file (never commit .env to Git)."
        )


def _basic_auth_header() -> dict:
    raw = f"{YAHOO_CLIENT_ID}:{YAHOO_CLIENT_SECRET}".encode()
    return {"Authorization": "Basic " + base64.b64encode(raw).decode()}


def _load_store() -> Optional[dict]:
    try:
        if TOKEN_STORE.is_file():
            return json.loads(TOKEN_STORE.read_text())
    except Exception:
        pass
    return None


def _save_store(payload: dict) -> None:
    TOKEN_STORE.parent.mkdir(parents=True, exist_ok=True)
    TOKEN_STORE.write_text(json.dumps(payload, indent=2))
    print(f"✅ Tokens saved to {TOKEN_STORE}")


# ------------------------------------
# Public API
# ------------------------------------
def build_authorization_url(state: str = "state") -> str:
    """Build the Yahoo consent URL for first-time setup."""
    _check_env()
    q = urlencode({
        "client_id": YAHOO_CLIENT_ID,
        "redirect_uri": YAHOO_REDIRECT_URI,
        "response_type": "code",
        "language": "en-us",
        "scope": "fspt-w",
        "state": state,
    })
    return f"{AUTH_URL}?{q}"


def exchange_code(code: str) -> OAuthTokens:
    """Exchange a one-time authorization code for access + refresh tokens."""
    _check_env()
    r = requests.post(TOKEN_URL, headers={
        **_basic_auth_header(),
        "Content-Type": "application/x-www-form-urlencoded",
    }, data={
        "grant_type": "authorization_code",
        "redirect_uri": YAHOO_REDIRECT_URI,
        "code": code,
    }, timeout=30)
    r.raise_for_status()
    j = r.json()

    payload = {
        "access_token": j["access_token"],
        "refresh_token": j.get("refresh_token"),
        "token_type": j.get("token_type", "Bearer"),
        "expires_in": j.get("expires_in", 3600),
        "expires_at": _now() + int(j.get("expires_in", 3600)),
    }
    _save_store(payload)
    return OAuthTokens(**payload)


def refresh_access_token(refresh_token: Optional[str] = None) -> OAuthTokens:
    """Refresh the access token. Saves updated tokens back to store."""
    _check_env()

    if not refresh_token:
        stored = _load_store() or {}
        refresh_token = stored.get("refresh_token") or os.getenv("YAHOO_REFRESH_TOKEN", "")

    if not refresh_token:
        raise RuntimeError(
            "No refresh token found. Run first-time setup:\n"
            "  python -m src.auth setup"
        )

    r = requests.post(TOKEN_URL, headers={
        **_basic_auth_header(),
        "Content-Type": "application/x-www-form-urlencoded",
    }, data={
        "grant_type": "refresh_token",
        "redirect_uri": YAHOO_REDIRECT_URI,
        "refresh_token": refresh_token,
    }, timeout=30)
    r.raise_for_status()
    j = r.json()

    expires_in = int(j.get("expires_in", 3600))
    payload = {
        "access_token": j["access_token"],
        "refresh_token": j.get("refresh_token", refresh_token),
        "token_type": j.get("token_type", "Bearer"),
        "expires_in": expires_in,
        "expires_at": _now() + expires_in,
    }
    _save_store(payload)
    return OAuthTokens(**payload)


def get_token() -> str:
    """
    Main entry point used everywhere in the app.
    Returns a valid access token string, refreshing automatically if needed.
    """
    stored = _load_store()

    # Use cached token if still fresh
    if stored and stored.get("access_token") and stored.get("expires_at"):
        if stored["expires_at"] - _now() > EXPIRY_SKEW:
            return stored["access_token"]
        # Token is stale — refresh it
        return refresh_access_token(stored.get("refresh_token")).access_token

    # No store — try refreshing from env var as fallback
    return refresh_access_token(os.getenv("YAHOO_REFRESH_TOKEN")).access_token


# ------------------------------------
# First-time setup (run once)
# ------------------------------------
def setup() -> None:
    """
    Interactive first-time OAuth setup.
    Run once to get your refresh token, then get_token() handles everything.
    """
    _check_env()
    url = build_authorization_url()
    print("\n🔐 Yahoo Fantasy OAuth Setup")
    print("=" * 50)
    print("1️⃣  Open this URL in your browser:")
    print(f"\n  {url}\n")
    print("2️⃣  Authorize the app, then paste the code below.")
    code = input("   Authorization code: ").strip()

    tokens = exchange_code(code)
    print(f"\n✅ Setup complete! Token saved to {TOKEN_STORE}")
    print("   From now on, just call get_token() — it auto-refreshes.")
    return tokens


# ------------------------------------
# Run as script: python -m src.auth setup
# ------------------------------------
if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "setup":
        setup()
    else:
        print("Usage: python -m src.auth setup")
        print("       (Run this once to authenticate with Yahoo)")
