# setup_oauth.py
import json
from requests_oauthlib import OAuth2Session
from pathlib import Path

# Path to oauth.json in the root directory
OAUTH_FILE = Path(__file__).parent.parent / "oauth.json"

# Load client ID and secret
with open(OAUTH_FILE) as f:
    creds = json.load(f)

CLIENT_ID = creds["client_id"]
CLIENT_SECRET = creds["client_secret"]
REDIRECT_URI = "oob"
AUTH_BASE = "https://api.login.yahoo.com/oauth2/request_auth"
TOKEN_URL = "https://api.login.yahoo.com/oauth2/get_token"

scope = ["fspt-w"]  # Fantasy Sports permission

yahoo = OAuth2Session(client_id=CLIENT_ID, redirect_uri=REDIRECT_URI, scope=scope)

# Step 1: Get authorization URL
auth_url, state = yahoo.authorization_url(AUTH_BASE)
print("Go to this URL in your browser and authorize the app:")
print(auth_url)

# Step 2: Paste the code from browser
code = input("Enter the code you received here: ")

# Step 3: Fetch the access token
token = yahoo.fetch_token(
    TOKEN_URL,
    code=code,
    client_id=CLIENT_ID,
    client_secret=CLIENT_SECRET,
)

# Step 4: Save token back to oauth.json
creds.update(token)  # add access_token, refresh_token, expires_at, etc.
with open(OAUTH_FILE, "w") as f:
    json.dump(creds, f, indent=2)

print(f"✅ Token saved to {OAUTH_FILE}")




