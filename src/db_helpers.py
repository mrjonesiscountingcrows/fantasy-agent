# src/db_helpers.py
import sqlite3
from pathlib import Path
import json

DB_PATH = Path("data/db.sqlite")

def get_conn():
    return sqlite3.connect(DB_PATH)

# ----------------------------
# League / Team Helpers
# ----------------------------
def insert_league(league_key, name, season, num_teams):
    with get_conn() as conn:
        conn.execute("""
            INSERT OR REPLACE INTO leagues (league_key, name, season, num_teams)
            VALUES (?, ?, ?, ?)
        """, (league_key, name, season, num_teams))
        conn.commit()

def insert_team(team_key, league_key, name, manager):
    with get_conn() as conn:
        conn.execute("""
            INSERT OR REPLACE INTO teams (team_key, league_key, name, manager)
            VALUES (?, ?, ?, ?)
        """, (team_key, league_key, name, manager))
        conn.commit()

# ----------------------------
# Player Helpers
# ----------------------------
def insert_player(player_key, name, position, team, status=None):
    with get_conn() as conn:
        conn.execute("""
            INSERT OR REPLACE INTO players (player_key, name, position, team, status)
            VALUES (?, ?, ?, ?, ?)
        """, (player_key, name, position, team, status))
        conn.commit()

# ----------------------------
# Roster Helpers
# ----------------------------
def insert_roster(team_key, player_key, week, slot):
    with get_conn() as conn:
        conn.execute("""
            INSERT INTO rosters (team_key, player_key, week, slot)
            VALUES (?, ?, ?, ?)
        """, (team_key, player_key, week, slot))
        conn.commit()

def get_roster(team_key, week):
    with get_conn() as conn:
        cur = conn.execute("""
            SELECT r.player_key, p.name, r.slot, p.position, p.team, p.status
            FROM rosters r
            JOIN players p ON r.player_key = p.player_key
            WHERE r.team_key = ? AND r.week = ?
        """, (team_key, week))
        return cur.fetchall()

# ----------------------------
# Projection Helpers
# ----------------------------
def insert_projection(player_key, week, projected_pts, projected_stats=None):
    with get_conn() as conn:
        conn.execute("""
            INSERT INTO projections (player_key, week, projected_pts, projected_stats)
            VALUES (?, ?, ?, ?)
        """, (player_key, week, projected_pts, json.dumps(projected_stats) if projected_stats else None))
        conn.commit()

def get_projection(player_key, week):
    with get_conn() as conn:
        cur = conn.execute("""
            SELECT projected_pts, projected_stats
            FROM projections
            WHERE player_key = ? AND week = ?
        """, (player_key, week))
        row = cur.fetchone()
        if not row:
            return None
        pts, stats_json = row
        return {
            "points": pts,
            "stats": json.loads(stats_json) if stats_json else {}
        }

def get_team_projections(team_key, week):
    with get_conn() as conn:
        cur = conn.execute("""
            SELECT p.player_key, p.name, r.slot, proj.projected_pts
            FROM rosters r
            JOIN players p ON r.player_key = p.player_key
            LEFT JOIN projections proj 
                   ON r.player_key = proj.player_key 
                  AND r.week = proj.week
            WHERE r.team_key = ? AND r.week = ?
        """, (team_key, week))
        return cur.fetchall()
    
# Add this (one time) where you set up your DB (e.g., src/db_helpers.py init)
def ensure_rag_tables(conn):
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS player_embeddings (
            player_key TEXT PRIMARY KEY,
            name TEXT,
            position TEXT,
            nfl_team TEXT,
            embedding BLOB
        );
    """)
    conn.commit()

