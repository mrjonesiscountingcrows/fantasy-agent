from src.get_access_token import get_access_token
from src.yahoo_client import get_league_standings

LEAGUE_KEY = "461.l.609166"

def main():
    try:
        access_token = get_access_token()
    except Exception as e:
        print(f"❌ Error obtaining access token: {e}")
        return

    try:
        standings = get_league_standings(access_token, LEAGUE_KEY)
    except Exception as e:
        print(f"❌ Error fetching league: {e}")
        return

    print(f"✅ League: {LEAGUE_KEY}")
    for i, team in enumerate(standings, 1):
        print(f"{i}. {team['name']} — Manager: {team['manager']} (team_key: {team['team_key']})")

if __name__ == "__main__":
    main()

