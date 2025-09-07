# src/db.py
import sqlite3
from pathlib import Path
import json
import time
from src.yahoo_client import get_league_standings, get_league_rosters, iter_league_players, get_players_projections_batch, get_matchups
from src.yahoo_auth import refresh_token
from typing import Optional

DB_PATH = Path("data/db.sqlite")
DB_PATH.parent.mkdir(parents=True, exist_ok=True)

SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS leagues (
    league_key TEXT PRIMARY KEY,
    name TEXT,
    season INTEGER,
    num_teams INTEGER
);

CREATE TABLE IF NOT EXISTS teams (
    team_key TEXT PRIMARY KEY,
    league_key TEXT NOT NULL,
    name TEXT,
    manager TEXT,
    wins INTEGER DEFAULT 0,
    losses INTEGER DEFAULT 0,
    ties INTEGER DEFAULT 0,
    points_for REAL DEFAULT 0,
    points_against REAL DEFAULT 0,
    FOREIGN KEY (league_key) REFERENCES leagues(league_key) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS players (
    player_key TEXT PRIMARY KEY,
    name TEXT,
    position TEXT,
    team TEXT,
    status TEXT
);

CREATE TABLE IF NOT EXISTS rosters (
    roster_id INTEGER PRIMARY KEY AUTOINCREMENT,
    team_key TEXT NOT NULL,
    player_key TEXT NOT NULL,
    week INTEGER NOT NULL,
    slot TEXT,
    FOREIGN KEY (team_key) REFERENCES teams(team_key) ON DELETE CASCADE,
    FOREIGN KEY (player_key) REFERENCES players(player_key) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_rosters_team_week ON rosters(team_key, week);

CREATE TABLE IF NOT EXISTS matchups (
    matchup_id INTEGER PRIMARY KEY AUTOINCREMENT,
    league_key TEXT NOT NULL,
    week INTEGER NOT NULL,
    team1_key TEXT NOT NULL,
    team2_key TEXT NOT NULL,
    team1_score REAL DEFAULT 0,
    team2_score REAL DEFAULT 0,
    winner TEXT,
    FOREIGN KEY (league_key) REFERENCES leagues(league_key) ON DELETE CASCADE,
    FOREIGN KEY (team1_key) REFERENCES teams(team_key) ON DELETE CASCADE,
    FOREIGN KEY (team2_key) REFERENCES teams(team_key) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS projections (
    projection_id INTEGER PRIMARY KEY AUTOINCREMENT,
    player_key TEXT NOT NULL,
    week INTEGER NOT NULL,
    projected_pts REAL,
    projected_stats JSON,
    FOREIGN KEY (player_key) REFERENCES players(player_key) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_projections_player_week ON projections(player_key, week);

CREATE TABLE IF NOT EXISTS player_embeddings (
    player_key TEXT PRIMARY KEY,
    name TEXT,
    position TEXT,
    nfl_team TEXT,
    embedding BLOB
);
"""

# ----------------------------
# DB Connection & Init
# ----------------------------
def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")
    return conn

def init_db():
    conn = get_conn()
    try:
        conn.executescript(SCHEMA)
        conn.commit()
        print("✅ Database initialized at", DB_PATH)
    finally:
        conn.close()

# ----------------------------
# Inserts
# ----------------------------
def insert_league(conn, league_key, name, season=None, num_teams=None):
    conn.execute("""
        INSERT OR REPLACE INTO leagues (league_key, name, season, num_teams)
        VALUES (?, ?, ?, ?)
    """, (league_key, name, season, num_teams))
    conn.commit()

def insert_team(conn, team_key, league_key, name, manager, wins=0, losses=0, ties=0):
    conn.execute("""
        INSERT OR REPLACE INTO teams (team_key, league_key, name, manager, wins, losses, ties)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (team_key, league_key, name, manager, wins, losses, ties))
    conn.commit()

def insert_player(conn, player_key, name, position, team, status=None):
    conn.execute("""
        INSERT OR REPLACE INTO players (player_key, name, position, team, status)
        VALUES (?, ?, ?, ?, ?)
    """, (player_key, name, position, team, status))
    conn.commit()

def insert_roster(conn, team_key, player_key, week, slot):
    conn.execute("""
        INSERT OR REPLACE INTO rosters (team_key, player_key, week, slot)
        VALUES (?, ?, ?, ?)
    """, (team_key, player_key, week, slot))
    conn.commit()

def insert_projection(conn, player_key, week, projected_pts, projected_stats=None):
    conn.execute("""
        INSERT INTO projections (player_key, week, projected_pts, projected_stats)
        VALUES (?, ?, ?, ?)
    """, (player_key, week, projected_pts, json.dumps(projected_stats) if projected_stats else None))
    conn.commit()

# ----------------------------
# Update League Data
# ----------------------------
def update_league_data(conn, token, league_key, week):
    """
    Pull league standings and rosters for a given week, insert into DB.
    """
    try:
        # Insert league placeholder
        insert_league(conn, league_key, "My League Name", 2025, 10)

        standings = get_league_standings(token, league_key)
        for team in standings:
            insert_team(conn,
                        team["team_key"],
                        league_key,
                        team["name"],
                        team["manager"],
                        wins=team.get("wins", 0),
                        losses=team.get("losses", 0),
                        ties=team.get("ties", 0))

            roster_data = get_league_rosters(token, league_key, week, team["team_key"],refresh_cb=refresh_token)
            players = roster_data[team["team_key"]]["players"]

            for player in players:
                insert_player(conn, player["player_key"], player["name"],
                              player["position"], player["nfl_team"], player.get("status"))
                insert_roster(conn, team["team_key"], player["player_key"], week, player.get("slot"))

        print(f"✅ League data updated for week {week}.")
    except Exception as e:
        print(f"❌ Failed to update league data: {e}")

# ----------------------------
# Update All Players (FA + pool)
# ----------------------------
def update_all_players(conn, token, league_key,
                       *, max_batches: int = None,
                       position: str = None,
                       status: str = None) -> int:
    """
    Pull the entire league player pool (drafted, free agents, waivers, etc.)
    and insert into DB.
    """
    count = 0
    try:
        for p in iter_league_players(token,
                                     league_key,
                                     batch_size=25,
                                     max_batches=max_batches,
                                     refresh_cb=refresh_token,
                                     status_filter=status,
                                     position_filter=position):
            insert_player(conn, p["player_key"], p["name"], p["position"], p["nfl_team"], p.get("status"))
            count += 1
        conn.commit()
        print(f"✅ Inserted/updated {count} players in DB.")
        return count
    except Exception as e:
        print(f"❌ Failed to update all players: {e}")
        return 0

def upsert_projection(conn, player_key: str, week: int, projected_pts: float, projected_stats=None):
    # ensure (player_key, week) is unique by delete+insert
    conn.execute("DELETE FROM projections WHERE player_key=? AND week=?", (player_key, week))
    conn.execute("""
        INSERT INTO projections (player_key, week, projected_pts, projected_stats)
        VALUES (?, ?, ?, ?)
    """, (player_key, week, projected_pts, json.dumps(projected_stats) if projected_stats else None))
    conn.commit()

def update_weekly_projections(conn, token: str, league_key: str, week: int) -> int:
    """
    Fetch projections for the player POOL (works even pre-draft).
    Limit to skill positions by default for speed; loosen if desired.
    """
    cur = conn.cursor()
    # Choose the positions you care about (expand to "DEF", "K" if you want)
    cur.execute("""
        SELECT player_key FROM players
        WHERE position IN ('QB','RB','WR','TE','K','DEF')
    """)
    player_keys = [row[0] for row in cur.fetchall()]
    print(f"🔎 Candidate players for projections (week {week}): {len(player_keys)}")

    count = 0
    CHUNK = 25
    for i in range(0, len(player_keys), CHUNK):
        chunk = player_keys[i:i+CHUNK]
        try:
            batch = get_players_projections_batch(token, chunk, week, refresh_cb=refresh_token)
            for proj in batch:
                upsert_projection(conn, proj["player_key"], proj["week"],
                                  proj["projected_pts"], proj["projected_stats"])
                count += 1
        except Exception as e:
            print(f"⚠️  batch {i//CHUNK + 1} failed for {len(chunk)} players: {e}")
        time.sleep(0.2)  # gentle throttle
    return count

def upsert_matchup(conn, league_key, week, team1_key, team2_key, team1_score=0.0, team2_score=0.0, winner=None):
    conn.execute("""
        INSERT OR REPLACE INTO matchups (league_key, week, team1_key, team2_key, team1_score, team2_score, winner)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (league_key, week, team1_key, team2_key, team1_score, team2_score, winner))
    conn.commit()

def update_matchups(conn, token, league_key, week):
    rows = get_matchups(token, league_key, week)
    for m in rows:
        upsert_matchup(conn, league_key, week,
                       m["team1_key"], m["team2_key"],
                       m["team1_score"], m["team2_score"], m["winner"])
    print(f"✅ Matchups updated for week {week}.")

def get_opponent_for_team(conn, league_key, week, team_key) -> Optional[str]:
    cur = conn.cursor()
    cur.execute("""
        SELECT CASE
                 WHEN team1_key = ? THEN team2_key
                 WHEN team2_key = ? THEN team1_key
               END AS opp_key
        FROM matchups
        WHERE league_key = ? AND week = ? AND (team1_key = ? OR team2_key = ?)
        LIMIT 1
    """, (team_key, team_key, league_key, week, team_key, team_key))
    row = cur.fetchone()
    if not row or not row[0]:
        return None
    opp_key = row[0]
    cur.execute("SELECT name FROM teams WHERE team_key = ?", (opp_key,))
    row2 = cur.fetchone()
    return row2[0] if row2 else opp_key