"""
src/config.py
Central configuration — league settings and environment variables.

All hardcoded values live here. Nothing else in the codebase should
define LEAGUE_KEY or CURRENT_WEEK directly.

To configure:
    Copy .env.example to .env and fill in your values.
    Set LEAGUE_KEY and CURRENT_WEEK in .env, or they fall back to the
    defaults below.
"""

import os
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


# ----------------------------------------
# Paths
# ----------------------------------------
ROOT_DIR = Path(__file__).parent.parent
DATA_DIR = ROOT_DIR / "data"
CONFIG_DIR = ROOT_DIR / "config"
DB_PATH = DATA_DIR / "db.sqlite"


# ----------------------------------------
# League settings
# ----------------------------------------
LEAGUE_KEY: str = os.getenv("LEAGUE_KEY", "461.l.609166")


def get_current_week() -> int:
    """
    Automatically determine the current NFL fantasy week.

    Uses CURRENT_WEEK from .env if set (useful for testing or
    running recaps for a past week). Otherwise calculates from
    the NFL season start date.

    NFL regular season typically starts the Thursday after Labor Day.
    Week 1 = Sept 5, 2025 for the 2025 season.
    """
    # Manual override via .env
    override = os.getenv("CURRENT_WEEK")
    if override and override.isdigit():
        return int(override)

    # Auto-calculate from season start
    # Update SEASON_START each year
    SEASON_START = datetime(2025, 9, 4)  # Thursday, Sept 4 2025
    today = datetime.now()

    if today < SEASON_START:
        return 1  # Pre-season, default to week 1

    delta_days = (today - SEASON_START).days
    week = (delta_days // 7) + 1
    return min(week, 18)  # Cap at 18 (regular season max)


# ----------------------------------------
# OpenAI settings
# ----------------------------------------
OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")
OPENAI_MODEL_CHAT: str = os.getenv("OPENAI_MODEL_CHAT", "gpt-4o-mini")
OPENAI_MODEL_EMBED: str = os.getenv("OPENAI_MODEL_EMBED", "text-embedding-3-small")


# ----------------------------------------
# Sanity check (import-time warning only)
# ----------------------------------------
def check_config() -> list[str]:
    """Return a list of any missing required config values."""
    missing = []
    if not LEAGUE_KEY:
        missing.append("LEAGUE_KEY")
    if not OPENAI_API_KEY:
        missing.append("OPENAI_API_KEY")
    if not os.getenv("YAHOO_CLIENT_ID"):
        missing.append("YAHOO_CLIENT_ID")
    if not os.getenv("YAHOO_CLIENT_SECRET"):
        missing.append("YAHOO_CLIENT_SECRET")
    return missing
