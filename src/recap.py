# src/recap.py
import openai
import os
from src.yahoo_client import get_league_standings, get_matchups, get_league_rosters, get_all_players
from src.get_access_token import get_access_token  # optional if using automatic token

# Set your OpenAI API key
openai.api_key = os.getenv("OPENAI_API_KEY")

def format_standings(standings):
    """Formats standings with rank, team name, manager, and record."""
    lines = []
    for i, team in enumerate(standings, 1):
        name = team.get("name", "Unknown")
        manager = team.get("manager", "Manager")
        wins = team.get("wins", 0)
        losses = team.get("losses", 0)
        ties = team.get("ties", 0)
        lines.append(f"{i}. {name} — Manager: {manager} ({wins}-{losses}-{ties})")
    return "\n".join(lines)

def format_matchups(matchups, standings):
    """Formats matchups with team names, manager names, and winner."""
    team_map = {team["team_key"]: team for team in standings}
    lines = []
    for m in matchups:
        t1 = team_map.get(m['team1_key'], {"name": m['team1_key'], "manager": "Manager"})
        t2 = team_map.get(m['team2_key'], {"name": m['team2_key'], "manager": "Manager"})

        winner_name = "tie" if m['winner'] == "tie" else team_map.get(m['winner'], {"name": m['winner']})["name"]

        lines.append(
            f"{t1['name']} ({t1['manager']}) [{m['team1_score']}] vs "
            f"{t2['name']} ({t2['manager']}) [{m['team2_score']}] — Winner: {winner_name}"
        )
    return "\n".join(lines)

def generate_recap(token: str, league_key: str, week: int):
    """Generates a fun, roast-filled recap for the given week, including manager names."""
    standings = get_league_standings(token, league_key)
    matchups = get_matchups(token, league_key, week)
    
    standings_str = format_standings(standings)
    matchups_str = format_matchups(matchups, standings) if matchups else "No matchups yet; league is still in predraft."

    prompt = f"""
You are a fantasy football league commissioner bot.
Summarize Week {week} results in a fun, roast-filled weekly recap.
Mention managers by name and include playful commentary about their teams.

Standings:
{standings_str}

Matchups:
{matchups_str}
"""
    resp = openai.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": "You are a witty, sarcastic fantasy football assistant who knows each manager's name."},
            {"role": "user", "content": prompt}
        ],
        temperature=0.9
    )

    return resp.choices[0].message.content

# ---------------- Chat Agent ----------------
from src.yahoo_client import get_all_players, get_league_standings, get_matchups
from src.recap import format_standings, format_matchups
import openai

def chat_league(token: str, league_key: str, week: int):
    """Interactive chat with your fantasy league data, including undrafted players."""
    standings = get_league_standings(token, league_key)
    matchups = get_matchups(token, league_key, week)
    all_players = get_all_players(token, league_key, week)

    print("Fantasy League Chat Agent 🚀")
    print("Type 'exit' to quit. You can ask questions like:")
    print("- Which players are on [team name]?")
    print("- Who is injured?")
    print("- Who scored the most points this week?")
    print("- Who is available at WR?\n")

    while True:
        question = input("You: ").strip()
        if question.lower() in ("exit", "quit"):
            break

        # Build a structured prompt with standings, matchups, and all players
        prompt = f"""
You are a fantasy football assistant. Answer questions based on the following league data:

Standings:
{format_standings(standings)}

Matchups:
{format_matchups(matchups, standings)}

Players:
"""
        for player in all_players.values():
            team_info = f"{player['team_name']} ({player['manager']})" if player['team_name'] else "Free Agent"
            prompt += f"- {player['name']} [{player['position']}, {player['status']}, {player.get('week_points', 0)} pts] — {team_info}\n"

        prompt += f"\nQuestion: {question}\nAnswer:"

        resp = openai.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "You are a helpful fantasy football assistant that knows all teams, managers, player stats, and free agents."},
                {"role": "user", "content": prompt}
            ],
            temperature=0
        )

        print("Assistant:", resp.choices[0].message.content, "\n")


