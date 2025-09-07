import sqlite3

conn = sqlite3.connect("data/db.sqlite")
cur = conn.cursor()

# list tables
cur.execute("SELECT name FROM sqlite_master WHERE type='table';")
print(cur.fetchall())

# peek projections
cur.execute("SELECT player_key, week, projected_pts FROM projections LIMIT 10;")
print(cur.fetchall())