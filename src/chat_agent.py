# src/chat_agent.py
import sqlite3
from typing import Optional, Dict, List
from openai import OpenAI
from src.yahoo_client import get_league_standings, get_matchups
from src.rag import search_players_semantic, fetch_player_fantasy_team, fetch_player_projection
from src.db import update_league_data
from src.db import update_matchups, get_opponent_for_team 

client = OpenAI()

def _find_team_by_name(standings: List[Dict], name_fragment: str) -> Optional[Dict]:
    name_fragment = name_fragment.lower()
    for t in standings:
        if name_fragment in t["name"].lower():
            return t
    return None

def _standings_context(standings: List[Dict]) -> str:
    lines = []
    for t in standings:
        lines.append(f"{t['name']} — {t['wins']}-{t['losses']}-{t.get('ties',0)} (Mgr: {t['manager']})")
    return "\n".join(lines)

def _get_roster_for_team(conn: sqlite3.Connection, team_key: str, week: Optional[int]) -> List[Dict]:
    cur = conn.cursor()
    if week is None:
        cur.execute("SELECT MAX(week) FROM rosters WHERE team_key=?", (team_key,))
        wk = cur.fetchone()[0]
    else:
        wk = week

    if wk is None:
        return []

    cur.execute("""
        SELECT p.player_key, p.name, p.position, p.team, r.slot
        FROM rosters r
        JOIN players p ON p.player_key = r.player_key
        WHERE r.team_key=? AND r.week=?
        ORDER BY r.slot
    """, (team_key, wk))
    rows = cur.fetchall()
    return [
        {"player_key": rk, "name": n, "position": pos, "nfl_team": nfl, "slot": slot}
        for rk, n, pos, nfl, slot in rows
    ]

def _format_context_from_players(conn, players: List[Dict], week: Optional[int]) -> str:
    lines = []
    for p in players:
        fantasy = fetch_player_fantasy_team(conn, p["player_key"], week=week)
        proj = fetch_player_projection(conn, p["player_key"], week) if week else None

        parts = [f"{p['name']} ({p['position']}, {p['nfl_team']})"]
        if fantasy:
            parts.append(f"fantasy team: {fantasy.get('team_name') or fantasy['team_key']} (manager: {fantasy.get('manager')})")
        else:
            parts.append("fantasy team: free agent")
        if proj:
            parts.append(f"projected_pts (week {week}): {proj['projected_pts']}")
        lines.append(" — ".join(parts))
    return "\n".join(lines)


def chat_with_league(conn: sqlite3.Connection, token: str, league_key: str, week: int):
    update_league_data(conn, token, league_key, week)
    update_matchups(conn, token, league_key, week)
    standings = get_league_standings(token, league_key)
    team_names = ", ".join([t["name"] for t in standings])

    print("Fantasy League Chat Agent 🤖")
    print("Type 'exit' to quit.")
    print("You can ask things like:")
    print(" • Who is on <team name>?")
    print(" • Which team has <player name>?")
    print(" • Tell me about <player name> (even if they’re a free agent).")
    print(f"\nTeams: {team_names}\n")

    while True:
        q = input("You: ").strip()
        if q.lower() in ("exit", "quit"):
            break

        # 1) Exact team roster question?
        #    Simple heuristic: if question contains "who is on" or "roster of"
        lowered = q.lower()
        if "who is on" in lowered or "roster of" in lowered or "players on" in lowered:
            # try to find the team mentioned
            # take last token chunk after 'on'/'of'
            team = None
            for t in standings:
                if t["name"].lower() in lowered:
                    team = t
                    break
            if not team:
                # fallback: fuzzy contains
                for t in standings:
                    if any(part in t["name"].lower() for part in lowered.split()):
                        team = t
                        break

            if team:
                roster = _get_roster_for_team(conn, team["team_key"], week)
                if not roster:
                    print(f"Agent: I couldn't find a roster for '{team['name']}' for week {week}.\n")
                    continue

                roster_text = ", ".join([f"{p['name']} ({p['position']})" for p in roster])
                print(f"Agent: {team['name']} (Manager: {team['manager']}) — {roster_text}\n")
                continue

        # 2) General question -> semantic retrieve top players and answer with that context
        top_players = search_players_semantic(conn, q, k=8)
        context = _format_context_from_players(conn, top_players, week=week)
        league_snapshot = _standings_context(standings)
        full_context = f"{context}\n\nCurrent Standings:\n{league_snapshot}"


        messages = [
        {
        "role": "system",
        "content": (
            "You are a fantasy football assistant.\n"
            "Priority order:\n"
            "1) When the question is about THIS Yahoo fantasy league (rosters, who owns a player, team records, matchups), "
            "use the provided LEAGUE CONTEXT as the source of truth.\n"
            "2) You MAY use your general football knowledge for rules, player backgrounds, roles, injuries, "
            "and strategy tips, but if league-specific info is required and missing from context, say you don't have it.\n"
            "3) Be helpful and concise. State clearly when a detail comes from the league database vs general knowledge.\n"
        )
        },
        {
        "role": "user",
        "content": (
            f"User question: {q}\n\n"
            "LEAGUE CONTEXT (players/teams found via DB search):\n"
            f"{full_context}\n\n"
            "Answer the question. If it involves league-specific facts (roster ownership, standings, week matchups), "
            "ground those in the LEAGUE CONTEXT. If it's general (rules, player roles, NFL background), "
            "use your knowledge, and call out where league data was or wasn't available."
        )
        }
    ]
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=messages,
            temperature=0.0
        )
        print("Agent:", resp.choices[0].message.content, "\n")


