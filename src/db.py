"""
src/db.py
Database layer — single source of truth for all SQLite operations.

Replaces: db.py, db_helpers.py, db_updater.py

Schema tables:
    leagues, teams, players, rosters, matchups, projections, player_embeddings
"""

import json
import sqlite3
import time
from pathlib import Path
from typing import Optional

from src.yahoo_client import (
    get_league_standings,
    get_league_rosters,
    get_matchups,
    get_players_projections_batch,
    iter_league_players,
)

DB_PATH = Path("data/db.sqlite")
DB_PATH.parent.mkdir(parents=True, exist_ok=True)

SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS leagues (
    league_key  TEXT PRIMARY KEY,
    name        TEXT,
    season      INTEGER,
    num_teams   INTEGER
);

CREATE TABLE IF NOT EXISTS teams (
    team_key       TEXT PRIMARY KEY,
    league_key     TEXT NOT NULL,
    name           TEXT,
    manager        TEXT,
    wins           INTEGER DEFAULT 0,
    losses         INTEGER DEFAULT 0,
    ties           INTEGER DEFAULT 0,
    points_for     REAL DEFAULT 0,
    points_against REAL DEFAULT 0,
    FOREIGN KEY (league_key) REFERENCES leagues(league_key) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS players (
    player_key TEXT PRIMARY KEY,
    name       TEXT,
    position   TEXT,
    team       TEXT,
    status     TEXT
);

CREATE TABLE IF NOT EXISTS rosters (
    roster_id  INTEGER PRIMARY KEY AUTOINCREMENT,
    team_key   TEXT NOT NULL,
    player_key TEXT NOT NULL,
    week       INTEGER NOT NULL,
    slot       TEXT,
    FOREIGN KEY (team_key)   REFERENCES teams(team_key)   ON DELETE CASCADE,
    FOREIGN KEY (player_key) REFERENCES players(player_key) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_rosters_team_week ON rosters(team_key, week);

CREATE TABLE IF NOT EXISTS matchups (
    matchup_id  INTEGER PRIMARY KEY AUTOINCREMENT,
    league_key  TEXT NOT NULL,
    week        INTEGER NOT NULL,
    team1_key   TEXT NOT NULL,
    team2_key   TEXT NOT NULL,
    team1_score REAL DEFAULT 0,
    team2_score REAL DEFAULT 0,
    winner      TEXT,
    FOREIGN KEY (league_key) REFERENCES leagues(league_key) ON DELETE CASCADE,
    FOREIGN KEY (team1_key)  REFERENCES teams(team_key)    ON DELETE CASCADE,
    FOREIGN KEY (team2_key)  REFERENCES teams(team_key)    ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_matchups_league_week ON matchups(league_key, week);

CREATE TABLE IF NOT EXISTS projections (
    projection_id INTEGER PRIMARY KEY AUTOINCREMENT,
    player_key    TEXT NOT NULL,
    week          INTEGER NOT NULL,
    projected_pts REAL,
    projected_stats JSON,
    FOREIGN KEY (player_key) REFERENCES players(player_key) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_projections_player_week ON projections(player_key, week);

CREATE TABLE IF NOT EXISTS player_embeddings (
    player_key TEXT PRIMARY KEY,
    name       TEXT,
    position   TEXT,
    nfl_team   TEXT,
    embedding  BLOB,
    text_hash  TEXT
);
"""


# ----------------------------------------
# Connection & Init
# ----------------------------------------
def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db() -> None:
    conn = get_conn()
    try:
        conn.executescript(SCHEMA)
        conn.commit()
        print(f"✅ Database ready at {DB_PATH}")
    finally:
        conn.close()


# ----------------------------------------
# Upsert helpers (write ops)
# ----------------------------------------
def _upsert_league(conn: sqlite3.Connection, league_key: str, name: str,
                   season: int = None, num_teams: int = None) -> None:
    conn.execute("""
        INSERT OR REPLACE INTO leagues (league_key, name, season, num_teams)
        VALUES (?, ?, ?, ?)
    """, (league_key, name, season, num_teams))


def _upsert_team(conn: sqlite3.Connection, team_key: str, league_key: str,
                 name: str, manager: str, wins: int = 0,
                 losses: int = 0, ties: int = 0,
                 points_for: float = 0, points_against: float = 0) -> None:
    conn.execute("""
        INSERT OR REPLACE INTO teams
            (team_key, league_key, name, manager, wins, losses, ties, points_for, points_against)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (team_key, league_key, name, manager, wins, losses, ties, points_for, points_against))


def _upsert_player(conn: sqlite3.Connection, player_key: str, name: str,
                   position: str, team: str, status: str = None) -> None:
    conn.execute("""
        INSERT OR REPLACE INTO players (player_key, name, position, team, status)
        VALUES (?, ?, ?, ?, ?)
    """, (player_key, name, position, team, status))


def _upsert_roster(conn: sqlite3.Connection, team_key: str, player_key: str,
                   week: int, slot: str) -> None:
    conn.execute("""
        INSERT OR IGNORE INTO rosters (team_key, player_key, week, slot)
        VALUES (?, ?, ?, ?)
    """, (team_key, player_key, week, slot))


def _upsert_projection(conn: sqlite3.Connection, player_key: str, week: int,
                       projected_pts: float, projected_stats: dict = None) -> None:
    conn.execute("DELETE FROM projections WHERE player_key=? AND week=?", (player_key, week))
    conn.execute("""
        INSERT INTO projections (player_key, week, projected_pts, projected_stats)
        VALUES (?, ?, ?, ?)
    """, (player_key, week, projected_pts,
          json.dumps(projected_stats) if projected_stats else None))


def _upsert_matchup(conn: sqlite3.Connection, league_key: str, week: int,
                    team1_key: str, team2_key: str,
                    team1_score: float = 0.0, team2_score: float = 0.0,
                    winner: str = None) -> None:
    conn.execute("""
        INSERT OR REPLACE INTO matchups
            (league_key, week, team1_key, team2_key, team1_score, team2_score, winner)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (league_key, week, team1_key, team2_key, team1_score, team2_score, winner))


# ----------------------------------------
# Read helpers (query ops)
# ----------------------------------------
def get_roster(conn: sqlite3.Connection, team_key: str, week: int) -> list:
    """Return all players on a team for a given week."""
    cur = conn.execute("""
        SELECT r.player_key, p.name, r.slot, p.position, p.team, p.status
        FROM rosters r
        JOIN players p ON r.player_key = p.player_key
        WHERE r.team_key = ? AND r.week = ?
    """, (team_key, week))
    return cur.fetchall()


def get_projection(conn: sqlite3.Connection, player_key: str, week: int) -> Optional[dict]:
    """Return projection for a single player/week."""
    cur = conn.execute("""
        SELECT projected_pts, projected_stats
        FROM projections WHERE player_key = ? AND week = ?
    """, (player_key, week))
    row = cur.fetchone()
    if not row:
        return None
    return {
        "projected_pts": row[0],
        "projected_stats": json.loads(row[1]) if row[1] else {},
    }


def get_team_projections(conn: sqlite3.Connection, team_key: str, week: int) -> list:
    """Return projected points for every rostered player on a team."""
    cur = conn.execute("""
        SELECT p.player_key, p.name, r.slot, proj.projected_pts
        FROM rosters r
        JOIN players p ON r.player_key = p.player_key
        LEFT JOIN projections proj
               ON r.player_key = proj.player_key AND r.week = proj.week
        WHERE r.team_key = ? AND r.week = ?
    """, (team_key, week))
    return cur.fetchall()


def get_opponent_for_team(conn: sqlite3.Connection, league_key: str,
                          week: int, team_key: str) -> Optional[str]:
    """Return the opponent team name for a given team/week."""
    cur = conn.execute("""
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
    cur2 = conn.execute("SELECT name FROM teams WHERE team_key = ?", (row[0],))
    row2 = cur2.fetchone()
    return row2[0] if row2 else row[0]


# ----------------------------------------
# Sync: league data (standings + rosters)
# ----------------------------------------
def update_league_data(conn: sqlite3.Connection, token: str,
                       league_key: str, week: int) -> None:
    """Pull standings and rosters from Yahoo and store in DB."""
    from src.auth import get_token as _refresh
    try:
        _upsert_league(conn, league_key, "My Fantasy League", 2025, 10)

        standings = get_league_standings(token, league_key)
        for team in standings:
            _upsert_team(
                conn,
                team["team_key"], league_key, team["name"], team["manager"],
                wins=team.get("wins", 0),
                losses=team.get("losses", 0),
                ties=team.get("ties", 0),
                points_for=team.get("points_for", 0),
                points_against=team.get("points_against", 0),
            )
            roster_data = get_league_rosters(
                token, league_key, week, team["team_key"], refresh_cb=_refresh
            )
            for player in roster_data[team["team_key"]]["players"]:
                _upsert_player(conn, player["player_key"], player["name"],
                               player["position"], player["nfl_team"],
                               player.get("status"))
                _upsert_roster(conn, team["team_key"], player["player_key"],
                               week, player.get("slot", "BN"))

        conn.commit()
        print(f"✅ League data updated for week {week}")
    except Exception as e:
        conn.rollback()
        print(f"❌ Failed to update league data: {e}")
        raise


# ----------------------------------------
# Sync: full player pool (FA + waivers)
# ----------------------------------------
def update_all_players(conn: sqlite3.Connection, token: str,
                       league_key: str, *, max_batches: int = None,
                       position: str = None, status: str = None) -> int:
    """Pull entire player pool and store in DB. Returns count of players upserted."""
    from src.auth import get_token as _refresh
    count = 0
    try:
        for p in iter_league_players(
            token, league_key, batch_size=25,
            max_batches=max_batches,
            refresh_cb=_refresh,
            status_filter=status,
            position_filter=position,
        ):
            _upsert_player(conn, p["player_key"], p["name"],
                           p["position"], p["nfl_team"], p.get("status"))
            count += 1
        conn.commit()
        print(f"✅ Player pool updated: {count} players")
        return count
    except Exception as e:
        conn.rollback()
        print(f"❌ Failed to update player pool: {e}")
        return 0


# ----------------------------------------
# Sync: weekly projections
# ----------------------------------------
def update_weekly_projections(conn: sqlite3.Connection, token: str,
                               league_key: str, week: int) -> int:
    """Fetch and store projections for all rostered players. Returns count upserted."""
    from src.auth import get_token as _refresh
    cur = conn.cursor()
    cur.execute("""
        SELECT player_key FROM players
        WHERE position IN ('QB','RB','WR','TE','K','DEF')
    """)
    player_keys = [row[0] for row in cur.fetchall()]
    print(f"🔎 Fetching projections for {len(player_keys)} players (week {week})")

    count = 0
    CHUNK = 25
    for i in range(0, len(player_keys), CHUNK):
        chunk = player_keys[i:i + CHUNK]
        try:
            batch = get_players_projections_batch(token, chunk, week, refresh_cb=_refresh)
            for proj in batch:
                _upsert_projection(conn, proj["player_key"], proj["week"],
                                   proj["projected_pts"], proj["projected_stats"])
                count += 1
        except Exception as e:
            print(f"⚠️  Projection batch {i // CHUNK + 1} failed: {e}")
        time.sleep(0.2)

    conn.commit()
    print(f"✅ Projections updated: {count} players")
    return count


# ----------------------------------------
# Sync: matchups
# ----------------------------------------
def update_matchups(conn: sqlite3.Connection, token: str,
                    league_key: str, week: int) -> None:
    """Pull matchup scores from Yahoo and store in DB."""
    from src.auth import get_token as _refresh
    try:
        rows = get_matchups(token, league_key, week, refresh_cb=_refresh)
        for m in rows:
            _upsert_matchup(conn, league_key, week,
                            m["team1_key"], m["team2_key"],
                            m["team1_score"], m["team2_score"], m["winner"])
        conn.commit()
        print(f"✅ Matchups updated for week {week}")
    except Exception as e:
        conn.rollback()
        print(f"❌ Failed to update matchups: {e}")
        raise
