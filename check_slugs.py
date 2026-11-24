import json, os, requests

NAMES = ["kinaxis", "rossvideo", "qnx", "cohere", "waabi", "xanadu", "tenstorrent",
         "shopify", "ciena", "nokia", "genesys", "mozilla"]   # add any company you like

ADZUNA_QUERIES = [
    "embedded software engineer",
    "firmware engineer",
    "embedded linux",
    "robotics software engineer",
    "machine learning engineer junior",
    "junior software developer",
    "new grad software engineer",
]

HEADERS = {"User-Agent": "personal-job-assistant/0.1"}

def get(url):
    try:
        r = requests.get(url, timeout=15, headers=HEADERS)
        return r.json() if r.ok else None
    except Exception:
        return None

def variants(n):
    return list(dict.fromkeys([n, n.replace(" ", ""), n.replace(" ", "-")]))

found = {"greenhouse": [], "lever": [], "ashby": []}
for name in NAMES:
    hit = False
    for v in variants(name):
        gh = get(f"https://boards-api.greenhouse.io/v1/boards/{v}/jobs")
        if isinstance(gh, dict) and v not in found["greenhouse"]:
            found["greenhouse"].append(v); hit = True
            print(f"{name:14} greenhouse:{v} ({len(gh.get('jobs', []))} jobs)")
        lv = get(f"https://api.lever.co/v0/postings/{v}?mode=json")
        if isinstance(lv, list) and v not in found["lever"]:
            found["lever"].append(v); hit = True
            print(f"{name:14} lever:{v} ({len(lv)} jobs)")
        ab = get(f"https://api.ashbyhq.com/posting-api/job-board/{v}")
        if isinstance(ab, dict) and v not in found["ashby"]:
            found["ashby"].append(v); hit = True
            print(f"{name:14} ashby:{v} ({len(ab.get('jobs', []))} jobs)")
    if not hit:
        print(f"{name:14} NOT FOUND (likely Workday/custom site, check its careers page URL)")

found["adzuna_queries"] = ADZUNA_QUERIES
with open("companies.json", "w", encoding="utf-8") as f:
    json.dump(found, f, indent=2)
print("\nWrote companies.json")