# src/rag.py
import os
import sqlite3
import hashlib
from typing import List, Dict, Optional

import numpy as np
from dotenv import load_dotenv
from openai import OpenAI

# ---------------------------
# Env + OpenAI client (lazy)
# ---------------------------
load_dotenv()

_client: Optional[OpenAI] = None
def _get_client() -> OpenAI:
    """Lazily initialize OpenAI client (avoids import-time NameError)."""
    global _client
    if _client is None:
        api_key = os.getenv("OPENAI_API_KEY")
        _client = OpenAI(api_key=api_key) if api_key else OpenAI()
    return _client


# ---------------------------
# Helpers for canonical text + hashing
# ---------------------------
def _canonical_player_text(name: Optional[str],
                           position: Optional[str],
                           nfl_team: Optional[str],
                           status: Optional[str]) -> str:
    return f"{name or ''} | {position or ''} | {nfl_team or ''} | status:{status or 'active'}".strip()

def _sha1(s: str) -> str:
    return hashlib.sha1(s.encode("utf-8")).hexdigest()


# ---------------------------
# DB Helpers for embeddings
# ---------------------------
def ensure_embedding_table(conn: sqlite3.Connection) -> None:
    """
    Ensure the player_embeddings table exists and includes a text_hash column
    so we can skip re-embedding unchanged players.
    """
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS player_embeddings (
            player_key TEXT PRIMARY KEY,
            name TEXT,
            position TEXT,
            nfl_team TEXT,
            embedding BLOB,
            text_hash TEXT
        );
    """)
    conn.commit()

    # Backfill migration for older DBs (add text_hash if missing)
    cur.execute("PRAGMA table_info(player_embeddings)")
    cols = {row[1] for row in cur.fetchall()}
    if "text_hash" not in cols:
        cur.execute("ALTER TABLE player_embeddings ADD COLUMN text_hash TEXT")
        conn.commit()


# ---------------------------
# Embedding utilities
# ---------------------------
def get_embedding(text: str) -> List[float]:
    """Return embedding vector for a given text."""
    client = _get_client()
    emb = client.embeddings.create(
        model="text-embedding-3-small",
        input=text
    ).data[0].embedding
    return emb

def _embed_to_blob(vec: List[float]) -> bytes:
    return np.array(vec, dtype=np.float32).tobytes()

def _blob_to_embed(blob: bytes) -> np.ndarray:
    return np.frombuffer(blob, dtype=np.float32)


def _ensure_embedding_schema(conn: sqlite3.Connection) -> None:
    # Back-compat shim in case any code still calls the old name
    ensure_embedding_table(conn)

# ---------------------------
# Index building (incremental)
# ---------------------------
def build_player_index_from_db(conn: sqlite3.Connection, only_changed: bool = True) -> int:
    """
    Build or refresh embeddings for players. Skips unchanged rows by comparing a text hash.
    """
    _ensure_embedding_schema(conn)

    cur = conn.cursor()
    # load existing text_hashes
    cur.execute("SELECT player_key, text_hash FROM player_embeddings")
    existing = dict(cur.fetchall())  # {player_key: text_hash}

    # pull current player data
    cur.execute("SELECT player_key, name, position, team, status FROM players WHERE name IS NOT NULL")
    rows = cur.fetchall()

    upsert_count = 0
    for player_key, name, position, nfl_team, status in rows:
        if not player_key or not name:
            continue

        text = _canonical_player_text(name, position, nfl_team, status)
        h = _sha1(text)

        # skip if unchanged
        if only_changed and existing.get(player_key) == h:
            continue

        # compute / update embedding
        vec = get_embedding(text)  # uses your OpenAI client
        cur.execute("""
            INSERT INTO player_embeddings (player_key, name, position, nfl_team, embedding, text_hash)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(player_key) DO UPDATE SET
              name=excluded.name,
              position=excluded.position,
              nfl_team=excluded.nfl_team,
              embedding=excluded.embedding,
              text_hash=excluded.text_hash
        """, (player_key, name, position, nfl_team, _embed_to_blob(vec), h))
        upsert_count += 1

    conn.commit()
    return upsert_count


# ---------------------------
# Semantic search
# ---------------------------
def search_players_semantic(conn: sqlite3.Connection, query: str, k: int = 8) -> List[Dict]:
    """Return top-k semantically similar players for a query."""
    q_vec = np.array(get_embedding(query), dtype=np.float32)

    cur = conn.cursor()
    cur.execute("SELECT player_key, name, position, nfl_team, embedding FROM player_embeddings")

    sims: List[Dict] = []
    for player_key, name, pos, nfl, blob in cur.fetchall():
        if not blob:
            continue
        vec = _blob_to_embed(blob)
        denom = float(np.linalg.norm(q_vec) * np.linalg.norm(vec))
        sim = float(np.dot(q_vec, vec) / denom) if denom else 0.0
        sims.append({
            "player_key": player_key,
            "name": name,
            "position": pos,
            "nfl_team": nfl,
            "score": sim
        })

    sims.sort(key=lambda x: -x["score"])
    return sims[:k]


# ---------------------------
# Fetch player's fantasy team
# ---------------------------
def fetch_player_fantasy_team(conn: sqlite3.Connection, player_key: str, week: Optional[int] = None) -> Optional[Dict]:
    """
    Return the fantasy team (team_key, team_name, manager) a player belongs to for a given week.
    If week is None, use the most recent week in the rosters table.
    """
    cur = conn.cursor()

    if week is None:
        cur.execute("""
            SELECT r.team_key, MAX(r.week)
            FROM rosters r
            WHERE r.player_key = ?
        """, (player_key,))
        row = cur.fetchone()
        if not row or not row[0]:
            return None
        team_key = row[0]
    else:
        cur.execute("""
            SELECT r.team_key
            FROM rosters r
            WHERE r.player_key = ? AND r.week = ?
        """, (player_key, week))
        row = cur.fetchone()
        if not row or not row[0]:
            return None
        team_key = row[0]

    # Fetch team details
    cur.execute("SELECT name, manager FROM teams WHERE team_key = ?", (team_key,))
    trow = cur.fetchone()
    if not trow:
        return {"team_key": team_key, "team_name": None, "manager": None}

    return {"team_key": team_key, "team_name": trow[0], "manager": trow[1]}

def fetch_player_projection(conn: sqlite3.Connection, player_key: str, week: int) -> Optional[Dict]:
    cur = conn.cursor()
    cur.execute(
        "SELECT projected_pts, projected_stats FROM projections WHERE player_key=? AND week=?",
        (player_key, week)
    )
    row = cur.fetchone()
    if not row:
        return None
    projected_pts, projected_stats = row
    return {"projected_pts": projected_pts, "projected_stats": projected_stats}

def fetch_player_projection_by_name(conn: sqlite3.Connection, name: str, week: int):
    cur = conn.cursor()
    cur.execute("SELECT player_key FROM players WHERE LOWER(name)=LOWER(?)", (name,))
    row = cur.fetchone()
    if not row:
        return None
    return fetch_player_projection(conn, row[0], week)



