import requests
import base64
import json
from pathlib import Path

# --- Step 0: Paths ---
PROJECT_ROOT = Path(__file__).parent.parent  # parent of src/
CONFIG_DIR = PROJECT_ROOT / "config"
CONFIG_DIR.mkdir(parents=True, exist_ok=True)
SECRETS_PATH = CONFIG_DIR / "secrets.json"

# --- Step 1: Add your app credentials ---
client_id = "dj0yJmk9Q3Q1UmZEUVF4cWo0JmQ9WVdrOVdEbDFPVnBaV1dJbWNHbzlNQT09JnM9Y29uc3VtZXJzZWNyZXQmc3Y9MCZ4PTU5"
client_secret = "f1202b68f7ec150ede0dd7483d8c7d58458b5ff7"

# --- Step 2: Generate the authorization URL ---
auth_url = (
    f"https://api.login.yahoo.com/oauth2/request_auth?"
    f"client_id={client_id}&redirect_uri=oob&response_type=code&language=en-us"
)

print("1️⃣ Open this URL in your browser and authorize your app:")
print(auth_url)

# --- Step 3: Paste the code from Yahoo ---
auth_code = input("2️⃣ Paste the authorization code here: ").strip()

# --- Step 4: Exchange for tokens ---
basic_auth = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
headers = {
    "Authorization": f"Basic {basic_auth}",
    "Content-Type": "application/x-www-form-urlencoded"
}
data = {
    "grant_type": "authorization_code",
    "code": auth_code,
    "redirect_uri": "oob"
}

response = requests.post("https://api.login.yahoo.com/oauth2/get_token", headers=headers, data=data)

try:
    response.raise_for_status()
except requests.exceptions.HTTPError as e:
    print("❌ Error exchanging authorization code for tokens:")
    print(response.text)
    raise e

tokens = response.json()
print("\n✅ Response from Yahoo:")
print(json.dumps(tokens, indent=2))

# --- Step 5: Save secrets ---
refresh_token = tokens.get("refresh_token")
if refresh_token:
    SECRETS_PATH.write_text(json.dumps({
        "client_id": client_id,
        "client_secret": client_secret,
        "refresh_token": refresh_token,
        "basic_auth": basic_auth
    }, indent=2))
    print(f"\nSaved refresh_token to {SECRETS_PATH}")
else:
    print("❌ No refresh_token found in response!")
