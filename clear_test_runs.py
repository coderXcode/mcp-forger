"""Clear all test runs from the database."""
import sqlite3

DB_PATH = "/app/data/mcp_forge.db"

conn = sqlite3.connect(DB_PATH)
cur = conn.cursor()

cur.execute("SELECT COUNT(*) FROM testrun")
count = cur.fetchone()[0]
print(f"Found {count} test run(s) — deleting...")

cur.execute("DELETE FROM testrun")
conn.commit()

cur.execute("SELECT COUNT(*) FROM testrun")
remaining = cur.fetchone()[0]
print(f"Done. Remaining: {remaining}")

conn.close()
