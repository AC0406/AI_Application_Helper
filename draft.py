import argparse, time
from pipeline import db, make_resume, notify

ap = argparse.ArgumentParser()
ap.add_argument("--min-score", type=int, default=40)
ap.add_argument("--top", type=int, default=3, help="draft resumes for the N best-scoring jobs")
args = ap.parse_args()

rows = db.execute(
    "SELECT id, title, company, description, score FROM jobs "
    "WHERE status IN ('scored', 'validation_failed') AND score >= ? "
    "ORDER BY score DESC LIMIT ?",
    (args.min_score, args.top),
).fetchall()

print(f"Drafting {len(rows)} resume(s)")
for id_, title, company, desc, score in rows:
    t0 = time.time()
    res = make_resume(dict(title=title, company=company, description=desc))
    if res:
        db.execute("UPDATE jobs SET resume=?, status='ready' WHERE id=?", (res.model_dump_json(), id_))
        status = "ready"
        notify(f"{title} @ {company} ({score}) ready for review")
    else:
        db.execute("UPDATE jobs SET status='validation_failed' WHERE id=?", (id_,))
        status = "validation_failed"
    db.commit()
    print(f"{score:3}  {title} @ {company}  [{status}]  {time.time() - t0:.0f}s")