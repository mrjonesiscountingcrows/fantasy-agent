"""
Fantasy Football Agent
Entry point: pulls Yahoo data, updates DB, generates recap, prints it, or opens chat agent.
"""

from pathlib import Path
from dotenv import load_dotenv  # 👈 add this

# Load environment variables from .env
load_dotenv()
from src.yahoo_auth import refresh_token
from src.recap import generate_recap
from src.chat_agent import chat_with_league  # RAG chat module
from src.db import init_db, get_conn, update_league_data, update_all_players, update_weekly_projections
from src.rag import build_player_index_from_db


DB_PATH = Path("data/db.sqlite")
LEAGUE_KEY = "461.l.609166"   # Replace with your Yahoo league key
CURRENT_WEEK = 1              # TODO: automate week detection

# --- Main Flow ---
def run():
    # Ensure database + tables exist
    init_db()

    # Get OAuth token
    try:
        token = refresh_token()
    except Exception as e:
        print(f"❌ Failed to get access token: {e}")
        return

    # Update database (teams, rosters, players, embeddings)
    conn = get_conn()
    try:
        print("📡 Updating league rosters and teams...")
        update_league_data(conn, token, LEAGUE_KEY, CURRENT_WEEK)

        print("📡 Updating full player pool (FA + waivers)...")
        players_changed = update_all_players(conn, token, LEAGUE_KEY)  # returns count

        print("📈 Updating weekly projections...")
        proj_count = update_weekly_projections(conn, token, LEAGUE_KEY, CURRENT_WEEK)
        print(f"✅ Upserted projections for {proj_count} rostered players this week.")

        print("🧠 Building semantic embeddings for all players...")
        emb_upserts = build_player_index_from_db(conn,only_changed=True)  # False forces embedding generation
        print(f"✅ Embeddings upserted: {emb_upserts} (players changed this run: {players_changed})")
    except Exception as e:
        print(f"❌ Failed to update database: {e}")
    finally:
        conn.close()

    # Ask user what to do next
    print("\nDo you want to (1) Generate a weekly recap or (2) Chat with the league agent?")
    choice = input("Enter 1 or 2: ").strip()

    if choice == "1":
        try:
            recap_text = generate_recap(token, LEAGUE_KEY, CURRENT_WEEK)
            print("\n🎯 WEEKLY RECAP 🎯\n")
            print(recap_text)
        except Exception as e:
            print(f"❌ Failed to generate recap: {e}")
    elif choice == "2":
        conn = get_conn()
        try:
            chat_with_league(conn, token, LEAGUE_KEY, CURRENT_WEEK)
        finally:
            conn.close()
    else:
        print("Invalid choice. Exiting.")


if __name__ == "__main__":
    run()
