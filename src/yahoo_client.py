# src/yahoo_client.py
import requests
import xml.etree.ElementTree as ET
import time
from typing import List, Callable, Optional, Dict, Any

BASE_URL = "https://fantasysports.yahooapis.com/fantasy/v2"

# ---------------- Helper ----------------
def _get_xml(token: str,
             url: str,
             *,
             max_retries: int = 3,
             refresh_cb: Optional[Callable[[], str]] = None) -> ET.Element:
    """GET Yahoo Fantasy XML with a browsery UA, optional refresh-on-401, and basic backoff."""
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/xml",
        "User-Agent": (
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "en-US,en;q=0.9",
        "Connection": "keep-alive",
    }
    backoff = 0.5
    did_refresh = False
    for attempt in range(max_retries):
        resp = requests.get(url, headers=headers, timeout=20)

        # 401 → try exactly one token refresh if callback provided
        if resp.status_code == 401:
            if refresh_cb and not did_refresh:
                try:
                    token = refresh_cb()
                    headers["Authorization"] = f"Bearer {token}"
                    did_refresh = True
                    resp = requests.get(url, headers=headers, timeout=20)
                except Exception as e:
                    snippet = (resp.text or "")[:200]
                    raise PermissionError(f"401 and refresh failed: {e}. Body: {snippet}")
            if resp.status_code == 401:
                snippet = (resp.text or "")[:200]
                raise PermissionError(f"401 Unauthorized from Yahoo. Body: {snippet}")

        # Transient / WAF-ish codes
        if resp.status_code in (403, 429, 500, 502, 503, 504):
            if attempt < max_retries - 1:
                time.sleep(backoff)
                backoff *= 2
                continue
            snippet = (resp.text or "")[:200]
            raise RuntimeError(f"{resp.status_code} from Yahoo after retries. Body: {snippet}")

        if not resp.ok:
            snippet = (resp.text or "")[:200]
            raise ValueError(f"HTTP {resp.status_code} from Yahoo. Body: {snippet}")

        # Guard: ensure we actually got XML (WAF often returns HTML)
        ctype = (resp.headers.get("Content-Type") or "").lower()
        first = (resp.text or "")[:200]
        if "xml" not in ctype and not resp.text.lstrip().startswith("<?xml"):
            raise ValueError(f"Expected XML but got {ctype or 'unknown'}. First bytes: {first}")

        try:
            return ET.fromstring(resp.text)
        except ET.ParseError as e:
            raise ValueError(f"Failed to parse XML: {e}. First bytes: {first}")

    # Should never reach here
    raise RuntimeError("Exhausted retries without returning XML")

def _find_text(elem: Optional[ET.Element], path: str, default: Any = None, ns: Optional[Dict[str, str]] = None):
    if elem is None:
        return default
    child = elem.find(path, ns)
    return child.text if child is not None else default

# ---------------- League Teams (fallback for standings) ----------------
def get_league_teams(token: str,
                     league_key: str,
                     refresh_cb: Optional[Callable[[], str]] = None) -> List[Dict[str, Any]]:
    """Lightweight fallback to list teams + managers when /standings is not available."""
    url = f"{BASE_URL}/league/{league_key}/teams"
    root = _get_xml(token, url, refresh_cb=refresh_cb)
    ns = {"y": root.tag.split("}")[0].strip("{")}

    teams: List[Dict[str, Any]] = []
    for t in root.findall(".//y:team", ns):
        team_key = t.findtext("y:team_key", default="Unknown", namespaces=ns)
        name = t.findtext("y:name", default="Unknown", namespaces=ns)
        managers = t.findall("y:managers/y:manager", ns)
        manager_names = [m.findtext("y:nickname", default="Manager", namespaces=ns) for m in managers] if managers else ["Manager"]
        teams.append({
            "team_key": team_key,
            "name": name,
            "manager": ", ".join(manager_names),
            "wins": 0, "losses": 0, "ties": 0,
            "points_for": 0.0, "points_against": 0.0,
        })
    return teams

# ---------------- League Standings ----------------
def get_league_standings(token: str,
                         league_key: str,
                         refresh_cb: Optional[Callable[[], str]] = None) -> List[Dict[str, Any]]:
    url = f"{BASE_URL}/league/{league_key}/standings"
    root = _get_xml(token, url, refresh_cb=refresh_cb)
    ns_uri = root.tag.split("}")[0].strip("{")
    ns = {"y": ns_uri}

    teams = root.findall(".//y:team", ns)
    if not teams:
        raise ValueError("No standings found in league XML. Check league key or token.")

    result: List[Dict[str, Any]] = []
    for team_elem in teams:
        team_key = _find_text(team_elem, "y:team_key", "Unknown", ns)
        name = _find_text(team_elem, "y:name", "Unknown", ns)

        manager_elems = team_elem.findall("y:managers/y:manager", ns)
        manager_names = [_find_text(m, "y:nickname", "Manager", ns) for m in manager_elems] if manager_elems else ["Manager"]
        manager = ", ".join(manager_names)

        outcome_elem = team_elem.find("y:team_standings/y:outcome_totals", ns)
        wins = int(_find_text(outcome_elem, "y:wins", 0, ns)) if outcome_elem is not None else 0
        losses = int(_find_text(outcome_elem, "y:losses", 0, ns)) if outcome_elem is not None else 0
        ties = int(_find_text(outcome_elem, "y:ties", 0, ns)) if outcome_elem is not None else 0
        points_for = float(_find_text(team_elem, "y:team_standings/y:points_for", 0, ns))
        points_against = float(_find_text(team_elem, "y:team_standings/y:points_against", 0, ns))

        result.append({
            "team_key": team_key,
            "name": name,
            "manager": manager,
            "wins": wins,
            "losses": losses,
            "ties": ties,
            "points_for": points_for,
            "points_against": points_against,
        })
    return result

# ---------------- Player & Roster ----------------
def get_league_rosters(token: str,
                       league_key: str,
                       week: int,
                       team_key: Optional[str] = None,
                       refresh_cb: Optional[Callable[[], str]] = None) -> Dict[str, Dict[str, Any]]:
    """
    Fetch rosters for all teams in a league, or a single team if team_key is provided.
    Returns {team_key: {team_name, manager, team_key, players: [...]}}.
    Tries /standings (with refresh) and falls back to /teams if /standings is blocked.
    """
    try:
        standings = get_league_standings(token, league_key, refresh_cb=refresh_cb)
    except PermissionError:
        standings = get_league_teams(token, league_key, refresh_cb=refresh_cb)

    league_rosters: Dict[str, Dict[str, Any]] = {}
    for team in standings:
        if team_key and team["team_key"] != team_key:
            continue

        current_team_key = team["team_key"]
        url = f"{BASE_URL}/team/{current_team_key}/roster;week={week}"
        root = _get_xml(token, url, refresh_cb=refresh_cb)
        ns = {"y": root.tag.split("}")[0].strip("{")}

        players: List[Dict[str, Any]] = []
        for player_elem in root.findall(".//y:player", ns):
            players.append({
                "player_key": _find_text(player_elem, "y:player_key", ns=ns),
                "name": _find_text(player_elem, "y:name/y:full", ns=ns),
                "position": _find_text(player_elem, "y:display_position", ns=ns),
                "nfl_team": _find_text(player_elem, "y:editorial_team_abbr", ns=ns),
                "status": _find_text(player_elem, "y:status", ns=ns),
                "week_points": float(_find_text(player_elem, "y:player_points/y:total", 0, ns=ns) or 0),
                "slot": _find_text(player_elem, "y:selected_position/y:position", "BN", ns=ns),
            })

        league_rosters[current_team_key] = {
            "team_key": current_team_key,
            "team_name": team["name"],
            "manager": team["manager"],
            "players": players,
        }

        if team_key:  # only one team requested
            break
        time.sleep(0.15)  # polite between-team throttle

    return league_rosters

def get_player_projection(token: str,
                          player_key: str,
                          week: int,
                          refresh_cb: Optional[Callable[[], str]] = None) -> Dict[str, Any]:
    """Single-player projections (kept for convenience)."""
    url = f"{BASE_URL}/player/{player_key}/stats;type=week;week={week};is_projected=true"
    root = _get_xml(token, url, refresh_cb=refresh_cb)
    ns = {"y": root.tag.split("}")[0].strip("{")}
    stats = root.findall(".//y:stat", ns)
    projected_pts = float(_find_text(root, ".//y:player_points/y:total", 0, ns=ns) or 0)
    stat_dict = {
        s.find("y:stat_id", ns).text: s.find("y:value", ns).text
        for s in stats if s.find("y:stat_id", ns) is not None
    }
    return {"player_key": player_key, "week": week, "projected_pts": projected_pts, "projected_stats": stat_dict}

def get_players_projections_batch(token: str,
                                  player_keys: List[str],
                                  week: int,
                                  refresh_cb: Optional[Callable[[], str]] = None) -> List[Dict[str, Any]]:
    """Batch projections using /players;player_keys=... endpoint."""
    keys = ",".join(player_keys)
    url = f"{BASE_URL}/players;player_keys={keys}/stats;type=week;week={week};is_projected=true"
    root = _get_xml(token, url, refresh_cb=refresh_cb)
    ns = {"y": root.tag.split("}")[0].strip("{")}

    out: List[Dict[str, Any]] = []
    for p in root.findall(".//y:player", ns):
        pk = p.findtext("y:player_key", default=None, namespaces=ns)
        projected_pts = float(p.findtext(".//y:player_points/y:total", default="0", namespaces=ns) or 0)
        stats = {
            s.findtext("y:stat_id", default="", namespaces=ns): s.findtext("y:value", default="", namespaces=ns)
            for s in p.findall(".//y:stat", ns)
        }
        if pk:
            out.append({"player_key": pk, "week": week, "projected_pts": projected_pts, "projected_stats": stats})
    return out

def get_team_projections(token: str,
                         league_key: str,
                         team_key: str,
                         week: int,
                         refresh_cb: Optional[Callable[[], str]] = None) -> List[Dict[str, Any]]:
    """Projections for all players on a specific team."""
    rosters = get_league_rosters(token, league_key, week, team_key=team_key, refresh_cb=refresh_cb)
    team_roster = rosters.get(team_key, {})
    players = team_roster.get("players", [])
    return [get_player_projection(token, p["player_key"], week, refresh_cb=refresh_cb) for p in players]

# ---------------- Matchups ----------------
def get_matchups(token: str,
                 league_key: str,
                 week: int,
                 refresh_cb: Optional[Callable[[], str]] = None) -> List[Dict[str, Any]]:
    url = f"{BASE_URL}/league/{league_key}/scoreboard;week={week}"
    root = _get_xml(token, url, refresh_cb=refresh_cb)
    ns = {"y": root.tag.split("}")[0].strip("{")}

    result: List[Dict[str, Any]] = []
    for matchup_elem in root.findall(".//y:matchup", ns):
        teams = matchup_elem.findall("y:team", ns)
        if len(teams) < 2:
            continue

        team1_elem, team2_elem = teams[0], teams[1]
        team1_key = _find_text(team1_elem, "y:team_key", ns=ns)
        team2_key = _find_text(team2_elem, "y:team_key", ns=ns)
        team1_score = float(_find_text(team1_elem, "y:team_points/y:total", 0, ns=ns) or 0)
        team2_score = float(_find_text(team2_elem, "y:team_points/y:total", 0, ns=ns) or 0)
        winner = (
            team1_key if team1_score > team2_score
            else team2_key if team2_score > team1_score
            else "tie"
        )
        result.append({
            "team1_key": team1_key,
            "team2_key": team2_key,
            "team1_score": team1_score,
            "team2_score": team2_score,
            "winner": winner
        })
    return result

# ---------------- All Players ----------------
def get_all_players(token: str,
                    league_key: str,
                    week: int,
                    refresh_cb: Optional[Callable[[], str]] = None) -> Dict[str, Dict[str, Any]]:
    """
    Returns a dict of all players in the league: drafted (with team info) and free agents.
    """
    league_rosters = get_league_rosters(token, league_key, week, refresh_cb=refresh_cb)
    all_players: Dict[str, Dict[str, Any]] = {}

    # Drafted players
    for team_info in league_rosters.values():
        for player in team_info["players"]:
            player_key = player["player_key"]
            all_players[player_key] = {
                **player,
                "team_key": team_info["team_key"],
                "team_name": team_info["team_name"],
                "manager": team_info["manager"]
            }

    # Free agents by position
    positions = ["QB", "RB", "WR", "TE", "K", "DEF"]
    for pos in positions:
        url = f"{BASE_URL}/league/{league_key}/players;position={pos}"
        root = _get_xml(token, url, refresh_cb=refresh_cb)
        ns = {"y": root.tag.split("}")[0].strip("{")}
        players = root.findall(".//y:player", ns)

        for p in players:
            player_key = _find_text(p, "y:player_key", ns=ns)
            if player_key not in all_players:
                name = _find_text(p, "y:name/y:full", ns=ns)
                position = _find_text(p, "y:display_position", ns=ns)
                nfl_team = _find_text(p, "y:editorial_team_abbr", ns=ns)
                status = _find_text(p, "y:status", ns=ns)
                all_players[player_key] = {
                    "player_key": player_key,
                    "name": name,
                    "position": position,
                    "nfl_team": nfl_team,
                    "status": status,
                    "team_key": None,
                    "team_name": None,
                    "manager": None
                }

        time.sleep(0.1)  # tiny throttle between position pages

    return all_players

def iter_league_players(token: str,
                        league_key: str,
                        batch_size: int = 25,
                        max_batches: Optional[int] = None,
                        status_filter: Optional[str] = None,
                        position_filter: Optional[str] = None,
                        refresh_cb: Optional[Callable[[], str]] = None):
    """
    Iterate all players in the league player pool (includes free agents, waivers, etc.).
    Yields dicts: {player_key, name, position, nfl_team, status}
    """
    start = 0
    batches = 0

    while True:
        url = f"{BASE_URL}/league/{league_key}/players;start={start};count={batch_size}"
        if status_filter:
            url += f";status={status_filter}"
        if position_filter:
            url += f";position={position_filter}"

        root = _get_xml(token, url, refresh_cb=refresh_cb)
        ns = {"y": root.tag.split("}")[0].strip("{")}

        player_elems = root.findall(".//y:player", ns)
        if not player_elems:
            break

        for p in player_elems:
            yield {
                "player_key": _find_text(p, "y:player_key", ns=ns),
                "name": _find_text(p, "y:name/y:full", ns=ns),
                "position": _find_text(p, "y:display_position", ns=ns),
                "nfl_team": _find_text(p, "y:editorial_team_abbr", ns=ns),
                "status": _find_text(p, "y:status", ns=ns),
            }

        start += batch_size
        batches += 1
        if max_batches and batches >= max_batches:
            break
        time.sleep(0.1)  # polite pagination throttle
