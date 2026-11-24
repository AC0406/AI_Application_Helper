import json
import sqlite3
import webbrowser


def main():
    db = sqlite3.connect("jobs.db")
    rows = db.execute(
        "SELECT id, title, company, url, score, reasons, resume "
        "FROM jobs WHERE status='ready' ORDER BY score DESC"
    ).fetchall()

    if not rows:
        total = db.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
        print(f"No jobs ready for review (total jobs in DB: {total}).")
        return

    print(f"Found {len(rows)} job(s) ready for review.\n")

    for id_, title, company, url, score, reasons, resume in rows:
        print(f"\n=== {title} @ {company} | Fit: {score}/100 ===")
        print(f"URL: {url}")
        if reasons:
            print("Fit Reasons:", ", ".join(json.loads(reasons)))
        print("\nTailored Resume JSON:")
        print(json.dumps(json.loads(resume), indent=2))

        while True:
            ans = input("\n[a]pprove / [s]kip / [q]uit > ").strip().lower()
            if ans in ("a", "s", "q"):
                break

        if ans == "q":
            break
        if ans == "a":
            with open(f"out_{id_}.json", "w", encoding="utf-8") as f:
                f.write(resume)
            webbrowser.open(url)
            db.execute("UPDATE jobs SET status='approved' WHERE id=?", (id_,))
            print(f"Saved out_{id_}.json and opened application link.")
        else:
            db.execute("UPDATE jobs SET status='skipped' WHERE id=?", (id_,))
            print("Skipped.")

        db.commit()


if __name__ == "__main__":
    main()