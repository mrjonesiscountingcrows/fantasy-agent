# build_embeddings.py
from src.db import get_conn
from src.rag import build_player_index_from_db

conn = get_conn()
count = build_player_index_from_db(conn)
print(f"✅ Embedded {count} players")
conn.close()
