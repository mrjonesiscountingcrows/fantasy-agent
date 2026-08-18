"""
src/cli.py
Main entry point for the Fantasy Agent.

Replaces: main.py, cli_new.py

Usage:
    python -m src.cli                  # interactive menu
    python -m src.cli recap            # generate weekly recap
    python -m src.cli chat             # open chat agent
    python -m src.cli sync             # sync league data only
    python -m src.cli setup            # first-time Yahoo OAuth setup
    python -m src.cli recap --week 3   # recap for a specific week
"""

import argparse
import sys

from dotenv import load_dotenv

load_dotenv()

from src.auth import get_token, setup as oauth_setup
from src.config import LEAGUE_KEY, check_config, get_current_week
from src.db import (
    get_conn,
    init_db,
    update_all_players,
    update_league_data,
    update_matchups,
    update_weekly_projections,
)
from src.rag import build_player_index_from_db


# ----------------------------------------
# Sync — pulls all fresh data from Yahoo
# ----------------------------------------
def run_sync(token: str, week: int, full: bool = False) -> None:
    """Pull latest league data from Yahoo and update the local DB."""
    conn = get_conn()
    try:
        print(f"\n📡 Syncing league data for week {week}...")
        update_league_data(conn, token, LEAGUE_KEY, week)
        update_matchups(conn, token, LEAGUE_KEY, week)

        if full:
            print("📡 Updating full player pool (this takes a minute)...")
            update_all_players(conn, token, LEAGUE_KEY)

        print("📈 Updating weekly projections...")
        proj_count = update_weekly_projections(conn, token, LEAGUE_KEY, week)
        print(f"✅ Projections updated: {proj_count} players")

        print("🧠 Rebuilding player embeddings...")
        emb_count = build_player_index_from_db(conn, only_changed=True)
        print(f"✅ Embeddings updated: {emb_count} players\n")
    finally:
        conn.close()


# ----------------------------------------
# Recap
# ----------------------------------------
def run_recap(token: str, week: int) -> None:
    """Generate and print a roast-filled weekly recap."""
    from src.agent import generate_recap
    print(f"\n🎯 Generating Week {week} recap...\n")
    recap = generate_recap(token, LEAGUE_KEY, week)
    print("=" * 60)
    print(recap)
    print("=" * 60 + "\n")


# ----------------------------------------
# Chat
# ----------------------------------------
def run_chat(token: str, week: int) -> None:
    """Launch the interactive chat agent."""
    from src.agent import chat_with_league
    conn = get_conn()
    try:
        chat_with_league(conn, token, LEAGUE_KEY, week)
    finally:
        conn.close()


# ----------------------------------------
# Interactive menu (no args given)
# ----------------------------------------
def interactive_menu(token: str, week: int) -> None:
    print(f"\n🏈 Fantasy Agent — Week {week}")
    print("=" * 40)
    print("1) Sync league data")
    print("2) Generate weekly recap")
    print("3) Chat with league agent")
    print("4) Sync + Recap (do both)")
    print("q) Quit")
    print("=" * 40)

    choice = input("Choose an option: ").strip().lower()

    if choice == "1":
        run_sync(token, week)
    elif choice == "2":
        run_recap(token, week)
    elif choice == "3":
        run_chat(token, week)
    elif choice == "4":
        run_sync(token, week)
        run_recap(token, week)
    elif choice == "q":
        print("Goodbye 👋")
        sys.exit(0)
    else:
        print("Invalid choice.")


# ----------------------------------------
# CLI entry point
# ----------------------------------------
def main() -> None:
    parser = argparse.ArgumentParser(
        prog="fantasy-agent",
        description="Yahoo Fantasy Football AI Agent",
    )
    parser.add_argument(
        "command",
        nargs="?",
        choices=["sync", "recap", "chat", "setup"],
        help="Command to run (default: interactive menu)",
    )
    parser.add_argument(
        "--week",
        type=int,
        default=None,
        help="Override the current week number",
    )
    parser.add_argument(
        "--full",
        action="store_true",
        help="Sync: also update the full player pool (slower)",
    )
    args = parser.parse_args()

    # First-time OAuth setup — no token needed
    if args.command == "setup":
        oauth_setup()
        return

    # Config check
    missing = check_config()
    if missing:
        print(f"❌ Missing config: {', '.join(missing)}")
        print("   Check your .env file (copy .env.example to get started)")
        sys.exit(1)

    # Init DB
    init_db()

    # Get token (auto-refreshes if needed)
    try:
        token = get_token()
    except Exception as e:
        print(f"❌ Auth failed: {e}")
        print("   Try running: python -m src.cli setup")
        sys.exit(1)

    # Determine week
    week = args.week or get_current_week()
    print(f"📅 Week: {week}  |  League: {LEAGUE_KEY}")

    # Route to command
    if args.command == "sync":
        run_sync(token, week, full=args.full)
    elif args.command == "recap":
        run_sync(token, week)
        run_recap(token, week)
    elif args.command == "chat":
        run_sync(token, week)
        run_chat(token, week)
    else:
        interactive_menu(token, week)


if __name__ == "__main__":
    main()
