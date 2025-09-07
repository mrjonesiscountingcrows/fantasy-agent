import requests
import json
from pathlib import Path

# Load your secrets
SECRETS_FILE = Path("../config/secrets.json")
secrets = json.load(SECRETS_FILE.open())

def refresh_token():
    """Refresh Yahoo access token using refresh_token."""
    url = "https://api.login.yahoo.com/oauth2/get_token"
    data = {
        "client_id": secrets["client_id"],
        "client_secret": secrets["client_secret"],
        "refresh_token": secrets["refresh_token"],
        "grant_type": "refresh_token"
    }
    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    r = requests.post(url, data=data, headers=headers)
    r.raise_for_status()
    return r.json()["access_token"]

def get_user_leagues(game_code="nfl"):
    """Fetch all leagues for the logged-in user for a given game."""
    access_token = refresh_token()
    url = f"https://fantasysports.yahooapis.com/fantasy/v2/users;use_login=1/games;game_keys={game_code}/leagues"
    headers = {"Authorization": f"Bearer {access_token}"}
    r = requests.get(url, headers=headers)
    r.raise_for_status()

    # Yahoo sometimes returns XML instead of JSON, so parse carefully
    # We’ll just print the response text so you can inspect
    print("Raw response (first 1000 chars):")
    print(r.text[:1000])

if __name__ == "__main__":
    get_user_leagues()
