"""
src/agent.py
All AI-powered features — chat agent and weekly recap.

Replaces: chat_agent.py, recap.py

Usage:
    from src.agent import chat_with_league, generate_recap
"""

import sqlite3
from typing import Dict, List, Optional

from openai import OpenAI

from src.db import get_opponent_for_team, update_league_data, update_matchups
from src.rag import (
    fetch_player_fantasy_team,
    fetch_player_projection,
    search_players_semantic,
)
from src.yahoo_client import get_league_standings, get_matchups

client = OpenAI()


# ----------------------------------------
# Formatting helpers (used by both recap + chat)
# ----------------------------------------
def _format_standings(standings: List[Dict]) -> str:
    lines = []
    for i, team in enumerate(standings, 1):
        record = f"{team.get('wins', 0)}-{team.get('losses', 0)}-{team.get('ties', 0)}"
        lines.append(f"{i}. {team['name']} — Manager: {team['manager']} ({record})")
    return "\n".join(lines)


def _format_matchups(matchups: List[Dict], standings: List[Dict]) -> str:
    team_map = {t["team_key"]: t for t in standings}
    lines = []
    for m in matchups:
        t1 = team_map.get(m["team1_key"], {"name": m["team1_key"], "manager": "?"})
        t2 = team_map.get(m["team2_key"], {"name": m["team2_key"], "manager": "?"})
        if m["winner"] == "tie":
            winner_name = "tie"
        else:
            winner_name = team_map.get(m["winner"], {}).get("name", m["winner"])
        lines.append(
            f"{t1['name']} ({t1['manager']}) [{m['team1_score']}] vs "
            f"{t2['name']} ({t2['manager']}) [{m['team2_score']}] — Winner: {winner_name}"
        )
    return "\n".join(lines)


def _standings_summary(standings: List[Dict]) -> str:
    """Compact one-line-per-team standings for chat context."""
    lines = []
    for t in standings:
        record = f"{t['wins']}-{t['losses']}-{t.get('ties', 0)}"
        lines.append(f"{t['name']} — {record} (Mgr: {t['manager']})")
    return "\n".join(lines)


# ----------------------------------------
# Chat agent helpers
# ----------------------------------------
def _find_team(standings: List[Dict], name_fragment: str) -> Optional[Dict]:
    """Fuzzy match a team by name fragment."""
    fragment = name_fragment.lower()
    for t in standings:
        if fragment in t["name"].lower():
            return t
    # word-level fallback
    for t in standings:
        if any(word in t["name"].lower() for word in fragment.split()):
            return t
    return None


def _get_roster(conn: sqlite3.Connection, team_key: str,
                week: Optional[int]) -> List[Dict]:
    """Fetch a team's roster for a given week from the DB."""
    cur = conn.cursor()
    if week is None:
        cur.execute("SELECT MAX(week) FROM rosters WHERE team_key=?", (team_key,))
        week = cur.fetchone()[0]
    if week is None:
        return []
    cur.execute("""
        SELECT p.player_key, p.name, p.position, p.team, r.slot
        FROM rosters r
        JOIN players p ON p.player_key = r.player_key
        WHERE r.team_key=? AND r.week=?
        ORDER BY r.slot
    """, (team_key, week))
    return [
        {"player_key": pk, "name": n, "position": pos, "nfl_team": nfl, "slot": slot}
        for pk, n, pos, nfl, slot in cur.fetchall()
    ]


def _build_player_context(conn: sqlite3.Connection, players: List[Dict],
                           week: Optional[int]) -> str:
    """Build a rich context string for a list of players."""
    lines = []
    for p in players:
        fantasy = fetch_player_fantasy_team(conn, p["player_key"], week=week)
        proj = fetch_player_projection(conn, p["player_key"], week) if week else None

        parts = [f"{p['name']} ({p['position']}, {p['nfl_team']})"]
        if fantasy:
            parts.append(
                f"fantasy team: {fantasy.get('team_name') or fantasy['team_key']} "
                f"(manager: {fantasy.get('manager')})"
            )
        else:
            parts.append("fantasy team: free agent")
        if proj:
            parts.append(f"projected pts (week {week}): {proj['projected_pts']}")
        lines.append(" — ".join(parts))
    return "\n".join(lines)


# ----------------------------------------
# Chat agent
# ----------------------------------------
def chat_with_league(conn: sqlite3.Connection, token: str,
                     league_key: str, week: int) -> None:
    """
    Interactive chat loop. Answers questions about rosters,
    players, standings, and matchups using RAG + GPT-4o-mini.
    """
    update_league_data(conn, token, league_key, week)
    update_matchups(conn, token, league_key, week)
    standings = get_league_standings(token, league_key)
    team_names = ", ".join(t["name"] for t in standings)

    print("\n🤖 Fantasy League Chat Agent")
    print("Type 'exit' to quit. Ask me anything about your league.")
    print("Examples:")
    print("  • Who is on <team name>?")
    print("  • Which team has <player name>?")
    print("  • Should I start <player A> or <player B>?")
    print("  • Who are the best available WRs?")
    print(f"\nTeams in your league: {team_names}\n")

    while True:
        q = input("You: ").strip()
        if not q or q.lower() in ("exit", "quit"):
            break

        lowered = q.lower()

        # --- Shortcut: roster lookup (no LLM needed) ---
        if any(phrase in lowered for phrase in ("who is on", "roster of", "players on")):
            team = _find_team(standings, lowered)
            if team:
                roster = _get_roster(conn, team["team_key"], week)
                if roster:
                    players_str = ", ".join(
                        f"{p['name']} ({p['position']})" for p in roster
                    )
                    print(f"Agent: {team['name']} (Manager: {team['manager']}) — {players_str}\n")
                else:
                    print(f"Agent: No roster found for '{team['name']}' week {week}.\n")
                continue

        # --- General: semantic search + GPT ---
        top_players = search_players_semantic(conn, q, k=8)
        player_context = _build_player_context(conn, top_players, week=week)
        standings_context = _standings_summary(standings)

        messages = [
            {
                "role": "system",
                "content": (
                    "You are a fantasy football assistant for a Yahoo league.\n"
                    "Priority order:\n"
                    "1) For league-specific questions (rosters, ownership, standings, matchups) "
                    "use the LEAGUE CONTEXT as ground truth.\n"
                    "2) For general football questions (player backgrounds, strategy, injuries) "
                    "use your own knowledge and flag when league data wasn't available.\n"
                    "3) Be concise and direct. No fluff."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Question: {q}\n\n"
                    f"LEAGUE CONTEXT:\n{player_context}\n\n"
                    f"STANDINGS:\n{standings_context}\n\n"
                    "Answer the question using the league context where relevant, "
                    "your football knowledge otherwise."
                ),
            },
        ]

        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=messages,
            temperature=0.0,
        )
        print(f"Agent: {resp.choices[0].message.content}\n")


# ----------------------------------------
# Weekly recap
# ----------------------------------------
def generate_recap(token: str, league_key: str, week: int) -> str:
    """
    Generate a fun, roast-filled weekly recap using standings
    and matchup results for the given week.
    """
    standings = get_league_standings(token, league_key)
    matchups = get_matchups(token, league_key, week)

    standings_str = _format_standings(standings)
    matchups_str = (
        _format_matchups(matchups, standings)
        if matchups
        else "No matchups yet — league may still be in pre-draft."
    )

    prompt = f"""You are a fantasy football league commissioner bot.
Write a Week {week} recap that is funny, sarcastic, and roast-heavy.
Call out managers by name. Mock the losers. Hype the winners (a little).
Keep it to 3-4 paragraphs.

Standings:
{standings_str}

Matchups:
{matchups_str}
"""

    resp = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {
                "role": "system",
                "content": (
                    "You are a witty, sarcastic fantasy football commissioner. "
                    "You know every manager by name and love to roast them."
                ),
            },
            {"role": "user", "content": prompt},
        ],
        temperature=0.9,
    )
    return resp.choices[0].message.content
