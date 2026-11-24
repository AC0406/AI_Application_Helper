import argparse, json, os, sqlite3, requests
from typing import Literal
from pydantic import BaseModel
from llm import ask, FAST, STRONG
import sources

with open("master_profile.json", encoding="utf-8") as f:
    PROFILE = json.load(f)

db = sqlite3.connect("jobs.db")
db.execute("""CREATE TABLE IF NOT EXISTS jobs(
    id TEXT PRIMARY KEY,
    title TEXT,
    company TEXT,
    url TEXT,
    description TEXT,
    score INT,
    reasons TEXT,
    resume TEXT,
    status TEXT DEFAULT 'new'
)""")


class FitRaw(BaseModel):          # what the LLM extracts
    min_years_required: int       # explicitly stated in the posting, 0 if none
    domain_overlap: int           # 0-10
    matched_skills: list[str]
    missing_critical: list[str]
    reasons: list[str]

class Fit(BaseModel):             # what the pipeline stores
    score: int
    reasons: list[str]

class Bullet(BaseModel):
    source_id: str                # must exist in master profile
    text: str

class Resume(BaseModel):
    summary: str
    skills: list[str]
    bullets: list[Bullet]

class Critique(BaseModel):
    verdict: Literal["ok", "revise"]
    issues: list[str]


valid_ids = {b["id"] for sec in ("experience", "projects") for e in PROFILE[sec] for b in e["bullets"]}
canonical_skills = {s.lower(): s for s in PROFILE["skills"]}

# Compact profile for the cheap scoring step (saves context window)
SCORING_PROFILE = {
    "location": PROFILE["contact"]["location"],
    "willing_to_relocate_to": PROFILE["contact"].get("relocation_locations", []),
    "targets": PROFILE["targets"],
    "education": [{k: e[k] for k in ("school", "degree", "grad")} for e in PROFILE["education"]],
    "skills": PROFILE["skills"],
    "experience": [
        {"role": e["role"], "org": e["org"], "highlights": [b["text"][:140] for b in e["bullets"]]}
        for e in PROFILE["experience"]
    ],
    "projects": [f"{p['name']} ({', '.join(p['tech'])})" for p in PROFILE["projects"]],
}


def score(job):
    raw = ask(
        f"CANDIDATE:\n{json.dumps(SCORING_PROFILE)}\n\n"
        f"JOB:\n{job['title']} at {job['company']} ({job['location']})\n{job['description'][:3500]}",
        FitRaw,
        "Extract facts from the posting. Do NOT judge seniority; the candidate is a new grad targeting "
        "entry-level, junior and internship roles. Fields:\n"
        "- min_years_required: the minimum years of experience the posting explicitly states; 0 if none "
        "(internships and new-grad roles are 0).\n"
        "- domain_overlap: 0-10, how close the day-to-day work is to embedded/firmware, Linux kernel and "
        "drivers, low-level C/C++, edge AI and computer vision, ML systems, robotics software, or general "
        "software development. 0 means unrelated (web frontend, EDA tools, sales).\n"
        "- matched_skills: skills from the candidate's skills list that the posting asks for or clearly "
        "uses. Copy the exact names from the list.\n"
        "- missing_critical: up to 4 explicit must-have requirements the candidate lacks.\n"
        "- reasons: 2-3 short sentences.",
        model=FAST,
    )
    matched = list(dict.fromkeys(
        canonical_skills[s.strip().lower()]
        for s in raw.matched_skills if s.strip().lower() in canonical_skills
    ))
    overlap = max(0, min(10, raw.domain_overlap))
    years = max(raw.min_years_required, sources.min_years_required(job["description"]))

    s = overlap * 6 + min(len(matched), 8) * 4
    s -= 8 * min(len(raw.missing_critical), 4)
    if years >= 5:
        s -= 40
    elif years >= 3:
        s -= 20
    elif years == 2:
        s -= 8
    s = max(0, min(100, s))

    summary = (f"overlap {overlap}/10 | matched {len(matched)} skills | "
               f"missing {len(raw.missing_critical)} | years required {years}")
    return Fit(score=s, reasons=[summary] + raw.reasons[:3])


def validate(res: Resume):
    errs = []
    normalized_skills, bad_skills = [], []
    for s in res.skills:
        key = s.strip().lower()
        if key in canonical_skills:
            normalized_skills.append(canonical_skills[key])
        else:
            bad_skills.append(s)
    if bad_skills:
        errs.append(f"Skills not in master profile: {bad_skills}")
    else:
        res.skills = list(dict.fromkeys(normalized_skills))

    if bad_ids := [b.source_id for b in res.bullets if b.source_id not in valid_ids]:
        errs.append(f"Unknown source_ids: {bad_ids}")
    return errs


def tailor(job, feedback=""):
    return ask(
        f"PROFILE:\n{json.dumps(PROFILE)}\n\nJOB:\n{job['title']} at {job['company']}\n"
        f"{job['description'][:3500]}\n\nFEEDBACK TO ADDRESS:\n{feedback}",
        Resume,
        "Select and reword bullets from the profile to match this job. Use ONLY facts in the "
        "profile. Pick the 5-7 most relevant bullets, omit bullets unrelated to the job, and put the "
        "most relevant first. Rewrite each bullet to start with a strong past-tense action verb and "
        "to use the posting's terminology where it is truthful, keeping every fact, tool, and number "
        "from the source bullet and adding none. Every bullet needs the source_id it came from. "
        "Skills: at most 12, copied exactly from the profile's skills list, most relevant first. "
        "Summary: exactly 2 sentences in resume style with no name and no pronouns, e.g. "
        "'Computer systems engineering graduate with hands-on experience in ...'. "
        "Never add skills, tools, employers, or metrics that are not in the profile.",
        model=STRONG,
    )


def critique(job, res):
    return ask(
        f"JOB:\n{job['description'][:3500]}\n\nRESUME:\n{res.model_dump_json(indent=1)}\n\n"
        f"ORIGINAL FACTS:\n{json.dumps(PROFILE)}",
        Critique,
        "You are a skeptical hiring manager screening 200 resumes. Flag weak or vague bullets, "
        "missed keywords from the posting, and ANY claim not supported by the original facts. "
        "verdict is 'ok' only if you'd shortlist this candidate.",
        model=STRONG,
    )


def make_resume(job, rounds=3):
    feedback = ""
    last_valid = None
    for _ in range(rounds):
        res = tailor(job, feedback)
        if errs := validate(res):
            feedback = "; ".join(errs)
            continue
        last_valid = res
        c = critique(job, res)
        if c.verdict == "ok":
            return res
        feedback = "\n".join(c.issues)
    return last_valid  # None if every round failed hard validation


def notify(msg):
    topic = os.environ.get("NTFY_TOPIC")
    if not topic:
        return
    try:
        requests.post(f"https://ntfy.sh/{topic}", data=msg.encode("utf-8"), timeout=10)
    except requests.RequestException as e:
        print(f"Notification failed: {e}")


def run(cfg, min_score=40, allow_intern=True, limit=None):
    jobs = (
        [j for s in cfg.get("greenhouse", []) for j in sources.greenhouse(s)]
        + [j for s in cfg.get("lever", []) for j in sources.lever(s)]
        + [j for s in cfg.get("ashby", []) for j in sources.ashby(s)]
        + [j for q in cfg.get("adzuna_queries", []) for j in sources.adzuna(q)]
    )
    seen = set()
    jobs = [j for j in jobs if not (j["id"] in seen or seen.add(j["id"]))]
    relevant = [j for j in jobs if sources.is_relevant(j, allow_intern)]
    new = [j for j in relevant if not db.execute("SELECT 1 FROM jobs WHERE id=?", (j["id"],)).fetchone()]
    print(f"Fetched {len(jobs)} jobs | {len(relevant)} passed filter | {len(new)} are new")
    if limit:
        new = new[:limit]
        print(f"--limit: processing only {len(new)}")

    for i, j in enumerate(new, 1):
        try:
            f = score(j)
            status, resume_json = "scored", None
            if f.score >= min_score:
                res = make_resume(j)
                if res:
                    resume_json, status = res.model_dump_json(), "ready"
                else:
                    status = "validation_failed"
        except Exception as e:  # one bad job shouldn't kill the whole run
            print(f"[{i}/{len(new)}] ERROR on {j['title']} @ {j['company']}: {e}")
            continue
        db.execute(
            "INSERT INTO jobs VALUES(?,?,?,?,?,?,?,?,?)",
            (j["id"], j["title"], j["company"], j["url"], j["description"],
             f.score, json.dumps(f.reasons), resume_json, status),
        )
        db.commit()
        print(f"[{i}/{len(new)}] {f.score:3}  {j['title']} @ {j['company']}  [{status}]  {f.reasons[0]}")
        if status == "ready":
            notify(f"{j['title']} @ {j['company']} ({f.score}) ready for review")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None, help="process at most N new jobs (for testing)")
    ap.add_argument("--min-score", type=int, default=55)
    ap.add_argument("--no-intern", action="store_true", help="skip intern/co-op postings")
    args = ap.parse_args()

    if not os.path.exists("companies.json"):
        raise SystemExit("companies.json not found. Run: python check_slugs.py")
    with open("companies.json", encoding="utf-8") as f:
        cfg = json.load(f)

    run(cfg, min_score=args.min_score, allow_intern=not args.no_intern, limit=args.limit)