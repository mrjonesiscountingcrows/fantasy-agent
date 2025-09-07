# src/db_updater.py
from src.yahoo_client import get_league_standings, get_league_rosters
from src.db_helpers import insert_player, insert_roster

def update_league_data(conn, token, league_key, week):
    cur = conn.cursor()

    # --- 1. Update teams / standings ---
    standings = get_league_standings(token, league_key)
    for team in standings:
        cur.execute("""
            INSERT OR REPLACE INTO teams (team_key, league_key, name, manager, wins, losses, ties)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            team["team_key"],
            league_key,
            team.get("name", "Unknown"),
            team.get("manager", "Manager"),
            team.get("wins", 0),
            team.get("losses", 0),
            team.get("ties", 0),
        ))

    # --- 2. Update rosters for each team ---
    for team in standings:
        league_rosters = get_league_rosters(token, league_key, week, team_key=team["team_key"])
        # league_rosters is a dict of {team_key: {...}}
        for t_key, roster_info in league_rosters.items():
            for player in roster_info["players"]:
                # Insert into players table
                insert_player(
                    player_key=player["player_key"],
                    name=player["name"],
                    position=player["position"],
                    team=player["nfl_team"],
                    status=player["status"]
                )
                # Insert roster slot
                insert_roster(
                    team_key=t_key,
                    player_key=player["player_key"],
                    week=week,
                    slot=player["slot"]
                )

    conn.commit()
    print(f"✅ League data updated for week {week}.")

