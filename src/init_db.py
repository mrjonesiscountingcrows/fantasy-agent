# src/init_db.py
import sqlite3
from pathlib import Path

DB_PATH = Path("data/db.sqlite")
DB_PATH.parent.mkdir(parents=True, exist_ok=True)

schema = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS leagues (
    league_key   TEXT PRIMARY KEY,
    name         TEXT,
    season       INTEGER,
    num_teams    INTEGER
);

CREATE TABLE IF NOT EXISTS teams (
    team_key         TEXT PRIMARY KEY,
    league_key       TEXT NOT NULL,
    name             TEXT,
    manager          TEXT,
    wins             INTEGER DEFAULT 0,
    losses           INTEGER DEFAULT 0,
    ties             INTEGER DEFAULT 0,
    points_for       REAL DEFAULT 0,
    points_against   REAL DEFAULT 0,
    FOREIGN KEY (league_key) REFERENCES leagues (league_key) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS players (
    player_key   TEXT PRIMARY KEY,
    name         TEXT,
    position     TEXT,
    team         TEXT,
    status       TEXT
);

CREATE TABLE IF NOT EXISTS matchups (
    matchup_id   INTEGER PRIMARY KEY AUTOINCREMENT,
    league_key   TEXT NOT NULL,
    week         INTEGER NOT NULL,
    team1_key    TEXT NOT NULL,
    team2_key    TEXT NOT NULL,
    team1_score  REAL DEFAULT 0,
    team2_score  REAL DEFAULT 0,
    winner       TEXT, -- team_key or 'tie' or NULL if not final
    FOREIGN KEY (league_key) REFERENCES leagues (league_key) ON DELETE CASCADE,
    FOREIGN KEY (team1_key)  REFERENCES teams (team_key)    ON DELETE CASCADE,
    FOREIGN KEY (team2_key)  REFERENCES teams (team_key)    ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS transactions (
    transaction_id TEXT PRIMARY KEY,
    league_key     TEXT NOT NULL,
    type           TEXT,        -- add, drop, trade, waiver
    player_in      TEXT,        -- player_key
    player_out     TEXT,        -- player_key
    team_key       TEXT,        -- who executed it
    timestamp      DATETIME,
    FOREIGN KEY (league_key) REFERENCES leagues (league_key) ON DELETE CASCADE
);

-- New: Rosters (team players per week)
CREATE TABLE IF NOT EXISTS rosters (
    roster_id   INTEGER PRIMARY KEY AUTOINCREMENT,
    team_key    TEXT NOT NULL,
    player_key  TEXT NOT NULL,
    week        INTEGER NOT NULL,
    slot        TEXT,              -- e.g., QB, WR, Bench
    FOREIGN KEY (team_key)   REFERENCES teams (team_key)    ON DELETE CASCADE,
    FOREIGN KEY (player_key) REFERENCES players (player_key) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_rosters_team_week ON rosters (team_key, week);

-- New: Projections (player projections per week)
CREATE TABLE IF NOT EXISTS projections (
    projection_id  INTEGER PRIMARY KEY AUTOINCREMENT,
    player_key     TEXT NOT NULL,
    week           INTEGER NOT NULL,
    projected_pts  REAL,
    projected_stats JSON,          -- raw JSON if needed
    FOREIGN KEY (player_key) REFERENCES players (player_key) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_projections_player_week ON projections (player_key, week);

-- Indexes for faster lookups
CREATE INDEX IF NOT EXISTS idx_teams_league          ON teams (league_key);
CREATE INDEX IF NOT EXISTS idx_matchups_league_week  ON matchups (league_key, week);
CREATE INDEX IF NOT EXISTS idx_transactions_league   ON transactions (league_key);
CREATE INDEX IF NOT EXISTS idx_players_position      ON players (position);
"""

def init_db():
    conn = sqlite3.connect(DB_PATH)
    try:
        conn.executescript(schema)
        conn.commit()
        print("✅ Database initialized at", DB_PATH)
    finally:
        conn.close()

if __name__ == "__main__":
    init_db()
