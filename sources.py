import html, os, re, requests

HEADERS = {"User-Agent": "personal-job-assistant/0.1"}


def _clean_html(raw: str) -> str:
    text = html.unescape(raw or "")
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _get(url: str, **kwargs):
    r = requests.get(url, timeout=20, headers=HEADERS, **kwargs)
    r.raise_for_status()
    return r


def _warn(tag: str, e: Exception):
    code = getattr(getattr(e, "response", None), "status_code", None)
    print(f"[{tag}] skipped ({code or e})")


def greenhouse(slug: str):
    try:
        data = _get(f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true").json()
        for j in data.get("jobs", []):
            yield dict(
                id=f"gh-{j['id']}",
                title=j["title"],
                company=slug,
                location=(j.get("location") or {}).get("name", ""),
                url=j["absolute_url"],
                description=_clean_html(j.get("content", "")),
            )
    except requests.RequestException as e:
        _warn(f"greenhouse:{slug}", e)


def lever(slug: str):
    try:
        data = _get(f"https://api.lever.co/v0/postings/{slug}?mode=json").json()
        if not isinstance(data, list):
            return
        for j in data:
            sections = [j.get("descriptionPlain", "")]
            for lst in j.get("lists", []):
                sections.append(f"{lst.get('text', '')}: {_clean_html(lst.get('content', ''))}")
            if j.get("additionalPlain"):
                sections.append(j["additionalPlain"])
            yield dict(
                id=f"lv-{j['id']}",
                title=j["text"],
                company=slug,
                location=(j.get("categories") or {}).get("location", "") or "",
                url=j["hostedUrl"],
                description="\n".join(s for s in sections if s).strip(),
            )
    except requests.RequestException as e:
        _warn(f"lever:{slug}", e)


def ashby(slug: str):
    try:
        data = _get(f"https://api.ashbyhq.com/posting-api/job-board/{slug}").json()
        for j in data.get("jobs", []):
            yield dict(
                id=f"ab-{j['id']}",
                title=j["title"],
                company=slug,
                location=j.get("location", "") or "",
                url=j.get("jobUrl", ""),
                description=j.get("descriptionPlain") or _clean_html(j.get("descriptionHtml", "")),
            )
    except requests.RequestException as e:
        _warn(f"ashby:{slug}", e)


def adzuna(query: str, where: str = "Canada", pages: int = 2, max_days_old: int = 7):
    app_id = os.environ.get("ADZUNA_APP_ID")
    app_key = os.environ.get("ADZUNA_APP_KEY")
    if not app_id or not app_key:
        print("[adzuna] skipped: ADZUNA_APP_ID / ADZUNA_APP_KEY not set")
        return
    for page in range(1, pages + 1):
        try:
            data = _get(
                f"https://api.adzuna.com/v1/api/jobs/ca/search/{page}",
                params={
                    "app_id": app_id,
                    "app_key": app_key,
                    "what": query,
                    "where": where,
                    "max_days_old": max_days_old,
                    "results_per_page": 50,
                },
            ).json()
            for j in data.get("results", []):
                yield dict(
                    id=f"az-{j['id']}",
                    title=j.get("title", ""),
                    company=(j.get("company") or {}).get("display_name", "Unknown"),
                    location=(j.get("location") or {}).get("display_name", ""),
                    url=j.get("redirect_url", ""),
                    description=_clean_html(j.get("description", "")),
                )
        except requests.RequestException as e:
            _warn(f"adzuna:{query}:p{page}", e)
            break


# ---------- title / location pre-filter (runs before any GPU work) ----------

INCLUDE_RE = re.compile(
    r"\b(engineer\w*|developer\w*|programmer\w*|embedded|firmware|software|robotics|"
    r"ai|ml|machine learning|systems|devops|sde)\b", re.I)
EXCLUDE_RE = re.compile(
    r"\b(senior|sr\.?|staff|principal|lead|manager|director|vp|head of|architect|"
    r"physical design|signal integrity|package design|technician|field applications|"
    r"sales|recruiter|marketing|ios|android|designer|analyst)\b", re.I)
INTERN_RE = re.compile(r"\b(intern|internship|co-?op)\b", re.I)
ALLOWED_LOC = ("canada", "ottawa", "toronto", "ontario", "remote", "hybrid")

# e.g. "3+ years of professional experience", "5 years of hands-on embedded experience"
YEARS_RE = re.compile(r"(\d{1,2})\s*\+?\s*(?:years?|yrs?)\b[^.\n]{0,80}?\bexperience", re.I)
MAX_YEARS = 3   # postings whose smallest stated requirement exceeds this are dropped


def min_years_required(text: str) -> int:
    nums = [int(m.group(1)) for m in YEARS_RE.finditer(text or "")]
    return min(nums) if nums else 0


def is_relevant(job: dict, allow_intern: bool = True) -> bool:
    title = job["title"]
    loc = (job.get("location") or "").lower()
    if EXCLUDE_RE.search(title):
        return False
    if not allow_intern and INTERN_RE.search(title):
        return False
    if not INCLUDE_RE.search(title):
        return False
    if loc and not any(place in loc for place in ALLOWED_LOC):
        return False
    if min_years_required(job.get("description", "")) > MAX_YEARS:
        return False
    return True