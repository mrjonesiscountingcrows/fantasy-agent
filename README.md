# Fantasy Agent: Refactor Guide

## New structure
src/
main.py # Typer CLI entrypoint
auth.py # OAuth + env config
db.py # DB init, helpers, maintenance
yahoo_client.py # Yahoo API wrapper
rag.py # Embeddings/RAG utilities
chat_agent.py # Conversation agent
recap.py # Weekly recap logic

## Commands
python -m src.main verify-league
python -m src.main populate-players
python -m src.main index-players
python -m src.main build-embeddings
python -m src.main recap-week --week 1
python -m src.main chat


## File mapping
- AUTH: `get_access_token.py`, `get_refresh_token.py`, `setup_oauth.py`, `yahoo_auth.py` → `auth.py`
- DB: `db_helpers.py`, `db_updater.py`, `init_db.py`, `check_tables.py` → `db.py`
- SCRIPTS: `populate_players.py`, `index_players.py`, `fetch_league_key.py`, `verify_league.py`, `build_embeddings.py` → CLI commands in `main.py`
- KEEP: `yahoo_client.py`, `chat_agent.py`, `recap.py`, `rag.py`, `db.py`

## Secrets
Create a `.env` (not committed):

YAHOO_CLIENT_ID=
YAHOO_CLIENT_SECRET=
YAHOO_REDIRECT_URI=
YAHOO_REFRESH_TOKEN=
OPENAI_API_KEY=
DATABASE_URL=sqlite:///data/db.sqlite
ENV=dev


