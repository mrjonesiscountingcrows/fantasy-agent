# src/populate_players.py
import sqlite3
from src.db import get_conn, update_league_data
from src.get_access_token import get_access_token

LEAGUE_KEY = "461.l.609166"  # your Yahoo league key
WEEK = 1

def main():
    token = get_access_token()
    conn = get_conn()
    try:
        update_league_data(conn, token, LEAGUE_KEY, WEEK)
    finally:
        conn.close()

if __name__ == "__main__":
    main()
