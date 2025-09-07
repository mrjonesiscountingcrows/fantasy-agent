# src/index_players.py
import argparse
import sqlite3
from pathlib import Path
from src.yahoo_client import iter_league_players
from src.rag import ensure_embedding_table, build_player_index_from_db
from src.get_access_token import get_access_token  # your working token refresh helper

DB_PATH = Path("data/db.sqlite")

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--league", required=True, help="Yahoo league key, e.g., 461.l.609166")
    parser.add_argument("--max-batches", type=int, default=None, help="Limit number of batches fetched from Yahoo")
    args = parser.parse_args()

    token = get_access_token()

    # 1) Pull all players into 'players'
    count = 0
    for _ in iter_league_players(token, args.league, batch_size=50, max_batches=args.max_batches):
        count += 1
    print(f"Pulled/updated {count} players into `players` table.")

    # 2) Build embeddings
    conn = sqlite3.connect(DB_PATH)
    ensure_embedding_table(conn)
    n = build_player_index_from_db(conn)
    print(f"Embedded {n} players into `player_embeddings`.")
    conn.close()

if __name__ == "__main__":
    main()
