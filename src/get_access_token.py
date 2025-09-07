import json
import requests
from pathlib import Path

SECRETS_PATH = Path(__file__).parent.parent / "config/secrets.json"

def get_access_token() -> str:
    """Get a fresh access token using the refresh token."""
    secrets = json.loads(SECRETS_PATH.read_text())
    client_id = secrets["client_id"]
    client_secret = secrets["client_secret"]
    refresh_token = secrets["refresh_token"]

    basic_auth = f"{client_id}:{client_secret}"
    import base64
    basic_auth_encoded = base64.b64encode(basic_auth.encode()).decode()

    headers = {
        "Authorization": f"Basic {basic_auth_encoded}",
        "Content-Type": "application/x-www-form-urlencoded"
    }

    data = {
        "grant_type": "refresh_token",
        "refresh_token": refresh_token
    }

    resp = requests.post("https://api.login.yahoo.com/oauth2/get_token", headers=headers, data=data)
    resp.raise_for_status()
    token_data = resp.json()
    return token_data["access_token"]
