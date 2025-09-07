from __future__ import annotations

import base64
import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, TypedDict

import requests
from dotenv import load_dotenv
from requests import Session

# --- Load env once (uses python-dotenv which you already have) ---
load_dotenv()  # reads .env at repo root

# --- Yahoo OAuth config from .env (placeholders OK for now) ---
YAHOO_CLIENT_ID     = os.getenv("YAHOO_CLIENT_ID", "")
YAHOO_CLIENT_SECRET = os.getenv("YAHOO_CLIENT_SECRET", "")
YAHOO_REDIRECT_URI  = os.getenv("YAHOO_REDIRECT_URI", "")

# Where to keep your tokens locally (ignored by Git)
TOKEN_STORE = Path(os.getenv("YAHOO_TOKEN_PATH", "config/yahoo_token.json"))

# Legacy token file we may auto-migrate from (if you had one earlier)
LEGACY_OAUTH_JSON = Path("oauth2.json")

# Yahoo endpoints
TOKEN_URL  = "https://api.login.yahoo.com/oauth2/get_token"
AUTH_URL   = "https://api.login.yahoo.com/oauth2/request_auth"  # build the consent URL manually

# Optional default scope (Yahoo ignores custom scopes for Fantasy in many cases, but include for completeness)
DEFAULT_SCOPE = "fspt-w"

# Safety margin before expiry (seconds). We’ll refresh if the token expires within this window.
EXPIRY_SKEW = 120


# -----------------------------
# Types & helpers
# -----------------------------
class TokenPayload(TypedDict, total=False):
    access_token: str
    refresh_token: str
    token_type: str
    expires_in: int
    expires_at: int  # epoch seconds when token expires


@dataclass
class OAuthTokens:
    access_token: str
    refresh_token: Optional[str] = None
    token_type: str = "Bearer"
    expires_in: Optional[int] = None
    expires_at: Optional[int] = None


def _check_env():
    missing = []
    if not YAHOO_CLIENT_ID:
        missing.append("YAHOO_CLIENT_ID")
    if not YAHOO_CLIENT_SECRET:
        missing.append("YAHOO_CLIENT_SECRET")
    if missing:
        raise RuntimeError(
            "Missing Yahoo OAuth env values: "
            + ", ".join(missing)
            + ". Put them in .env (kept out of Git)."
        )


def _basic_auth_header() -> dict[str, str]:
    # Yahoo requires HTTP Basic (client_id:client_secret) for the token endpoint
    raw = f"{YAHOO_CLIENT_ID}:{YAHOO_CLIENT_SECRET}".encode()
    return {"Authorization": "Basic " + base64.b64encode(raw).decode()}


def _load_store() -> Optional[TokenPayload]:
    try:
        if TOKEN_STORE.is_file():
            return json.loads(TOKEN_STORE.read_text())
    except Exception:
        pass
    # Fallback: legacy oauth2.json
    try:
        if LEGACY_OAUTH_JSON.is_file():
            # We only care about the refresh_token; structure may vary
            data = json.loads(LEGACY_OAUTH_JSON.read_text())
            if isinstance(data, dict) and "refresh_token" in data:
                return {"refresh_token": data["refresh_token"]}
    except Exception:
        pass
    return None


def _save_store(payload: TokenPayload) -> None:
    TOKEN_STORE.parent.mkdir(parents=True, exist_ok=True)
    TOKEN_STORE.write_text(json.dumps(payload, indent=2))


def _now() -> int:
    return int(time.time())


# -----------------------------
# Public API
# -----------------------------
def build_authorization_url(state: str = "state", scope: str = DEFAULT_SCOPE) -> str:
    """
    Build the Yahoo consent URL. Use this when you need to get an authorization `code`
    for the very first time (one-time, manual step). After that, we live off refresh tokens.
    """
    _check_env()
    from urllib.parse import urlencode

    q = urlencode(
        {
            "client_id": YAHOO_CLIENT_ID,
            "redirect_uri": YAHOO_REDIRECT_URI,
            "response_type": "code",
            "language": "en-us",
            "scope": scope,
            "state": state,
        }
    )
    return f"{AUTH_URL}?{q}"


def exchange_code_for_tokens(code: str) -> OAuthTokens:
    """
    One-time step: exchange an authorization code for access+refresh tokens,
    save to TOKEN_STORE, and return them.
    """
    _check_env()
    headers = {
        **_basic_auth_header(),
        "Content-Type": "application/x-www-form-urlencoded",
    }
    data = {
        "grant_type": "authorization_code",
        "redirect_uri": YAHOO_REDIRECT_URI,
        "code": code,
    }
    r = requests.post(TOKEN_URL, headers=headers, data=data, timeout=30)
    r.raise_for_status()
    j = r.json()

    expires_at = _now() + int(j.get("expires_in", 3600))
    payload: TokenPayload = {
        "access_token": j["access_token"],
        "refresh_token": j.get("refresh_token"),
        "token_type": j.get("token_type", "Bearer"),
        "expires_in": j.get("expires_in", 3600),
        "expires_at": expires_at,
    }
    _save_store(payload)
    return OAuthTokens(
        access_token=payload["access_token"],
        refresh_token=payload.get("refresh_token"),
        token_type=payload.get("token_type", "Bearer"),
        expires_in=payload.get("expires_in"),
        expires_at=payload.get("expires_at"),
    )


def refresh_access_token(refresh_token: Optional[str] = None) -> OAuthTokens:
    """
    Refresh the access token using a refresh_token.
    Uses (in order): provided arg, TOKEN_STORE, YAHOO_REFRESH_TOKEN env.
    Persists the updated tokens to TOKEN_STORE.
    """
    _check_env()

    if not refresh_token:
        stored = _load_store() or {}
        refresh_token = stored.get("refresh_token") or os.getenv("YAHOO_REFRESH_TOKEN", "")

    if not refresh_token:
        raise RuntimeError(
            "No refresh_token found. Run first-time auth with build_authorization_url() "
            "and exchange_code_for_tokens()."
        )

    headers = {
        **_basic_auth_header(),
        "Content-Type": "application/x-www-form-urlencoded",
    }
    data = {
        "grant_type": "refresh_token",
        "redirect_uri": YAHOO_REDIRECT_URI,
        "refresh_token": refresh_token,
    }
    r = requests.post(TOKEN_URL, headers=headers, data=data, timeout=30)
    r.raise_for_status()
    j = r.json()

    new_refresh = j.get("refresh_token", refresh_token)
    expires_in = int(j.get("expires_in", 3600))
    payload: TokenPayload = {
        "access_token": j["access_token"],
        "refresh_token": new_refresh,
        "token_type": j.get("token_type", "Bearer"),
        "expires_in": expires_in,
        "expires_at": _now() + expires_in,
    }
    _save_store(payload)

    return OAuthTokens(
        access_token=payload["access_token"],
        refresh_token=payload["refresh_token"],
        token_type=payload["token_type"],
        expires_in=payload["expires_in"],
        expires_at=payload["expires_at"],
    )


def ensure_access_token() -> OAuthTokens:
    """
    Ensure we have a non-expired access token.
    - If store has a fresh token, use it.
    - If store has an almost-expired token, refresh it.
    - Else, try env refresh token.
    """
    stored = _load_store()
    if stored and "access_token" in stored and "expires_at" in stored:
        if stored["expires_at"] - _now() > EXPIRY_SKEW:
            # still good, return it
            return OAuthTokens(
                access_token=stored["access_token"],
                refresh_token=stored.get("refresh_token"),
                token_type=stored.get("token_type", "Bearer"),
                expires_in=stored.get("expires_in"),
                expires_at=stored.get("expires_at"),
            )
        # else refresh
        return refresh_access_token(stored.get("refresh_token"))

    # no store yet; try env-provided refresh token
    return refresh_access_token(os.getenv("YAHOO_REFRESH_TOKEN"))


def get_session() -> Session:
    """
    Return a requests.Session with a valid Authorization header.
    Refreshes if needed. Call this before Yahoo API calls.
    """
    tok = ensure_access_token()
    s = requests.Session()
    s.headers.update({"Authorization": f"{tok.token_type} {tok.access_token}"})
    return s
