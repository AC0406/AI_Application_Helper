import json, sqlite3

db = sqlite3.connect("jobs.db")
rows = db.execute("SELECT score, status, title, company, reasons FROM jobs ORDER BY score DESC").fetchall()
for score, status, title, company, reasons in rows:
    print(f"{score:3}  {status:17} {title} @ {company}")
    for r in json.loads(reasons or "[]")[:3]:
        print(f"       - {r}")
print(f"\n{len(rows)} jobs total")