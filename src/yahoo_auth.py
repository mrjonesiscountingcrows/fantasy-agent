# src/yahoo_auth.py
import requests
import json
from pathlib import Path

SECRETS_FILE = Path("config/secrets.json")

def load_secrets():
    return json.load(SECRETS_FILE.open())

def refresh_token():
    secrets = load_secrets()
    url = "https://api.login.yahoo.com/oauth2/get_token"
    headers = {"Authorization": f"Basic {secrets['basic_auth']}"}
    data = {
        "grant_type": "refresh_token",
        "redirect_uri": "oob",
        "refresh_token": secrets["refresh_token"]
    }
    r = requests.post(url, headers=headers, data=data)
    r.raise_for_status()
    token_data = r.json()
    return token_data["access_token"]
