from __future__ import annotations
import importlib, runpy
from typing import Iterable, Optional
import os, sys, runpy, typer

app = typer.Typer(help="Fantasy Agent (shim CLI wrapping existing scripts)")

def _run_module_with_argv(mod: str, argv: list[str]):
    """Run a module as __main__ with a temporary sys.argv, then restore it."""
    old_argv = sys.argv[:]
    try:
        sys.argv = [mod, *argv]
        # Avoid the "found in sys.modules" warning/noise
        return runpy.run_module(mod, run_name="__main__", alter_sys=True)
    finally:
        sys.argv = old_argv

def _call_module(module: str, func_candidates: Iterable[str] = ()):
    """
    Try calling a function from an existing module; if not found, run it as a script.
    This lets us wrap 'populate_players.py', etc., without changing them yet.
    """
    mod_name = f"src.{module}" if not module.startswith("src.") else module
    try:
        mod = importlib.import_module(mod_name)
        for name in func_candidates:
            if hasattr(mod, name):
                fn = getattr(mod, name)
                return fn()  # if it needs args, we’ll add later
    except Exception:
        # Fall back to running the module's __main__
        pass
    return runpy.run_module(mod_name, run_name="__main__")

@app.command()
def verify_league():
    """
    Wraps your existing verify_league.py (or similar) so you can call it via one CLI.
    """
    _call_module("verify_league", func_candidates=("main", "verify_league"))

@app.command()
def populate_players():
    _call_module("populate_players", func_candidates=("main", "run", "populate"))

# ------ index players (accept args and forward) ------
@app.command("index-players")
@app.command("index_players")  # allow underscore too
def index_players(
    league: str = typer.Option(
        default=os.getenv("LEAGUE_KEY", None),
        help="Yahoo league key (e.g., 461.l.609166). If omitted, uses $LEAGUE_KEY from .env when set.",
    ),
    max_batches: int = typer.Option(
        default=None,
        help="Optional: limit number of batches (for testing).",
    ),
):
    if not league:
        raise typer.BadParameter(
            "Missing --league and no $LEAGUE_KEY set in environment/.env"
        )
    argv = ["--league", league]
    if max_batches is not None:
        argv += ["--max-batches", str(max_batches)]
    _run_module_with_argv("src.index_players", argv)

# ------ build embeddings (silence the runtime warning) ------
@app.command("build-embeddings")
@app.command("build_embeddings")  # allow underscore too
def build_embeddings():
    _run_module_with_argv("src.build_embeddings", [])

@app.command()
def recap(week: Optional[int] = typer.Option(None, help="Week number")):
    # If your recap.py exposes a function we can pass week into, we’ll wire that in step 4.
    _call_module("recap", func_candidates=("main", "run", "recap"))

@app.command()
def chat():
    _call_module("chat_agent", func_candidates=("main", "run"))

if __name__ == "__main__":
    app()
