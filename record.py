"""Records REAL answers from the three sources into tests/fixtures/.

Run it BY HAND, only when you want fresh recordings:   python record.py
The tests never run it. It saves only the address, the status number and the body of each answer,
never any headers, so no secret could ever end up in a recording.
crt.sh is unreliable, so it is retried until we catch the answer we want (a good answer, an empty answer, or a real 502 error).
"""

import json
import sys
import time
from datetime import date
from pathlib import Path

import requests

FIXTURES = Path(__file__).parent / "tests" / "fixtures"
EXISTING_NAME = "example.com"
UNKNOWN_NAME = "this-does-not-exist-zzqq1234.com"
RECORD_TYPES = {"A": 1, "AAAA": 28, "NS": 2, "MX": 15, "TXT": 16}
USER_AGENT = "ioc-simple-dns/0.1 (training project; recorder)"


def fetch(url, params=None):
    """Send one request. Redirects are followed BY HAND so that every step is recorded. Returns a list of steps."""
    steps = []
    for _ in range(5):
        response = requests.get(url, params=params, allow_redirects=False, timeout=60, headers={"User-Agent": USER_AGENT})
        step = {"url": response.url, "status": response.status_code}
        if response.is_redirect:
            step["location"] = response.headers["Location"]
            steps.append(step)
            url, params = step["location"], None  # next step: go where the redirect points
            continue
        step["body"] = response.text
        steps.append(step)
        return steps
    raise RuntimeError("too many redirects")


def save(source, case, steps, note=None):
    folder = FIXTURES / source
    folder.mkdir(parents=True, exist_ok=True)
    document = {"recorded": date.today().isoformat(), "steps": steps}
    if note:
        document["note"] = note
    path = folder / f"{case}.json"
    path.write_text(json.dumps(document, indent=2, ensure_ascii=False) + "\n")
    print(f"saved {path.relative_to(FIXTURES.parent.parent)} ({path.stat().st_size} bytes)", flush=True)


def scrub_emails(steps):
    """Remove certificate rows whose names contain e-mail addresses (other people's personal data). Returns a note, or None."""
    last = steps[-1]
    rows = json.loads(last["body"])
    if not isinstance(rows, list):
        return None
    kept = []
    for row in rows:
        if "@" not in row.get("name_value", "") and "@" not in row.get("common_name", ""):
            kept.append(row)
    if len(kept) == len(rows):
        return None
    last["body"] = json.dumps(kept, separators=(",", ":"))
    return f"Real crt.sh answer. {len(rows) - len(kept)} of {len(rows)} certificate rows were removed because their names contain e-mail addresses (privacy)."


def record_dns(case, name):
    steps = []
    for number in RECORD_TYPES.values():
        steps += fetch("https://dns.google/resolve", {"name": name, "type": number})
    save("dns", case, steps)


def record_rdap(case, name):
    save("rdap", case, fetch(f"https://rdap.org/domain/{name}"))


def record_crtsh(case, name, is_wanted_answer, attempts=25):
    """Ask crt.sh again and again until its answer is the kind we want to record."""
    for attempt in range(1, attempts + 1):
        started = time.time()
        try:
            steps = fetch("https://crt.sh/", {"q": name, "output": "json"})
        except requests.RequestException as problem:
            print(f"  crt.sh attempt {attempt}: {type(problem).__name__}", flush=True)
            time.sleep(3)
            continue
        status = steps[-1]["status"]
        print(f"  crt.sh attempt {attempt}: HTTP {status} in {time.time() - started:.1f}s", flush=True)
        if is_wanted_answer(steps[-1]):
            note = scrub_emails(steps) if status == 200 else None
            save("crtsh", case, steps, note)
            return True
        time.sleep(3)
    print(f"  could not record crtsh/{case} after {attempts} attempts", flush=True)
    return False


def is_502(step):
    return step["status"] == 502


def is_a_good_answer(step):
    return step["status"] == 200 and len(json.loads(step["body"])) > 0


def is_an_empty_answer(step):
    return step["status"] == 200 and json.loads(step["body"]) == []


CASES = {
    "dns": lambda: (record_dns("hit", EXISTING_NAME), record_dns("unknown", UNKNOWN_NAME)),
    "rdap": lambda: (record_rdap("hit", EXISTING_NAME), time.sleep(2), record_rdap("unknown", UNKNOWN_NAME)),
    "crtsh_hit": lambda: record_crtsh("hit", EXISTING_NAME, is_a_good_answer),
    "crtsh_unknown": lambda: record_crtsh("unknown", UNKNOWN_NAME, is_an_empty_answer),
    "crtsh_error": lambda: record_crtsh("error_502", EXISTING_NAME, is_502, attempts=60),
}

if __name__ == "__main__":
    # "python record.py" records everything. "python record.py crtsh_error" records just that one case.
    wanted = sys.argv[1:] or list(CASES)
    for case_name in wanted:
        print(case_name, flush=True)
        CASES[case_name]()
