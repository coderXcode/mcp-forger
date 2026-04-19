import sqlite3
c = sqlite3.connect('/app/data/mcp_forge.db')
c.execute("UPDATE project SET status='ERROR' WHERE status='ANALYZING'")
c.commit()
print(c.execute('SELECT id, name, status FROM project').fetchall())
