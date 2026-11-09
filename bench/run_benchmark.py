"""Fixed-run benchmark: how many outbound HTTP requests does one fixed list of lookups cause?

Run it from the project folder:

    python bench/run_benchmark.py before      # on the code WITHOUT the cache -> bench/results/before.json
    python bench/run_benchmark.py after       # on the code WITH the cache    -> bench/results/after.json
    python bench/run_benchmark.py compare     # print both tables and check the answers did not change

Why it spends no real quota:
  * every outbound request is answered by a fake web (the `responses` library) that replays the recordings
    in tests/fixtures/, exactly like the tests do;
  * real sockets are switched off, so a request that escaped the fake web would crash instead of being sent.

Why the numbers can be trusted: the list below never changes, and the script only talks to the Flask app
through its test client, so the SAME file runs before and after caching. Only the cache differs.
"""

import json
import sys
from collections import Counter
from pathlib import Path
from urllib.parse import parse_qs, quote, urlparse

import responses
from pytest_socket import disable_socket

PROJECT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT))  # so "import backend" works when the script is run as bench/run_benchmark.py

from backend.app import app  # noqa: E402  (must come after the sys.path line above)

FIXTURES = PROJECT / "tests" / "fixtures"
RESULTS = Path(__file__).parent / "results"

# Names the fake web treats specially. Every other name gets the recorded "hit" answers.
UNKNOWN = "this-does-not-exist-zzqq1234.com"  # the recorded "unknown" answers: not found everywhere
FLAKY = "flaky.example.net"  # DNS and RDAP answer normally, crt.sh answers with the recorded 502 error

# THE FIXED LIST. Do not edit it between the "before" and the "after" run.
WORKLOAD = [
    # one name typed six different ways (case, spaces, trailing dot)
    "example.com", "example.com", "EXAMPLE.COM", " example.com ", "example.com.", "Example.Com.",
    # more names, with repeats and spelling variants
    "example.org", "example.org", "EXAMPLE.ORG",
    "example.net", "example.net.",
    "github.com", "github.com", "GitHub.com",
    # a name that does not exist (an answer: "not found"), asked three times
    UNKNOWN, UNKNOWN, UNKNOWN.upper(),
    # a name whose crt.sh lookup fails: errors must never be served from the cache
    FLAKY, FLAKY, FLAKY,
    # input the app rejects before it contacts anyone
    "10.0.0.1", "not a domain",
    # the same names again at the end, to see whether the cache still answers
    "example.com", "example.org", "github.com", "example.net", UNKNOWN,
]


def load_steps(source, case):
    return json.loads((FIXTURES / source / f"{case}.json").read_text())["steps"]


def source_of(url):
    """Which source does this outbound request belong to? (The RDAP redirect hop counts as RDAP.)"""
    host = urlparse(url).hostname
    if host == "dns.google":
        return "dns"
    if host == "crt.sh":
        return "crtsh"
    return "rdap"  # rdap.org and the registry it redirects to (rdap.verisign.com ...)


def install_fake_web(fake_web):
    """Teach the fake web to answer ANY name by replaying the recordings (the tests' recordings are for one name only)."""
    dns_steps = {}  # (case, record type number) -> recorded step
    for case in ("hit", "unknown"):
        for step in load_steps("dns", case):
            number = parse_qs(urlparse(step["url"]).query)["type"][0]
            dns_steps[(case, number)] = step
    rdap_first = {case: load_steps("rdap", case)[0] for case in ("hit", "unknown")}  # the 302 from rdap.org
    rdap_last = {case: load_steps("rdap", case)[1] for case in ("hit", "unknown")}  # the registry's answer
    crtsh_step = {
        "hit": load_steps("crtsh", "hit")[0],
        "unknown": load_steps("crtsh", "unknown")[0],
        "error": load_steps("crtsh", "error_502")[0],
    }

    def case_for(name):
        return "unknown" if name.lower() == UNKNOWN else "hit"

    def dns_answer(request):
        query = parse_qs(urlparse(request.url).query)
        case = case_for(query["name"][0])
        step = dns_steps[(case, query["type"][0])]
        # The recordings keep no headers, so add the Cache-Control Google really sent (checked 2026-11-06):
        # 300 s for an existing name, 900 s for a name that does not exist.
        header = "private, max-age=300" if case == "hit" else "private, max-age=900"
        return step["status"], {"Cache-Control": header}, step["body"]

    def rdap_redirect(request):
        step = rdap_first[case_for(urlparse(request.url).path.rsplit("/", 1)[-1])]
        return step["status"], {"Location": step["location"]}, step.get("body", "")

    def rdap_registry(request):
        step = rdap_last[case_for(urlparse(request.url).path.rsplit("/", 1)[-1])]
        return step["status"], {}, step.get("body", "")

    def crtsh_answer(request):
        name = parse_qs(urlparse(request.url).query)["q"][0]
        if name == FLAKY:
            step = crtsh_step["error"]
        else:
            step = crtsh_step[case_for(name)]
        return step["status"], {}, step["body"]

    fake_web.add_callback(responses.GET, "https://dns.google/resolve", callback=dns_answer, match_querystring=False)
    fake_web.add_callback(responses.GET, "https://crt.sh/", callback=crtsh_answer, match_querystring=False)
    # rdap.org redirects to the registry; the registry (any host/path under .../domain/...) gives the answer
    import re
    fake_web.add_callback(responses.GET, re.compile(r"https://rdap\.org/domain/.*"), callback=rdap_redirect)
    fake_web.add_callback(responses.GET, re.compile(r"https://rdap\.verisign\.com/.*"), callback=rdap_registry)


def clear_cache_if_any():
    """After caching exists, start every run with an empty cache. Before it exists, there is nothing to clear."""
    try:
        from backend.cache import clear_cache
    except ImportError:
        return
    clear_cache()


def run(label):
    disable_socket()  # any real connection attempt now raises an error
    clear_cache_if_any()
    client = app.test_client()
    lookups = []
    with responses.RequestsMock(assert_all_requests_are_fired=False) as fake_web:
        install_fake_web(fake_web)
        for typed in WORKLOAD:
            reply = client.get("/api/v1/domain/" + quote(typed))
            lookups.append({"typed": typed, "http_status": reply.status_code, "body": reply.get_json()})
        counts = Counter(source_of(call.request.url) for call in fake_web.calls)

    result = {
        "label": label,
        "lookups_made": len(WORKLOAD),
        "requests_per_source": {name: counts.get(name, 0) for name in ("dns", "rdap", "crtsh")},
        "requests_total": sum(counts.values()),
        "lookups": lookups,
    }
    RESULTS.mkdir(exist_ok=True)
    (RESULTS / f"{label}.json").write_text(json.dumps(result, indent=2))
    print_table(result)


def print_table(result):
    print(f"\n{result['label']}: {result['lookups_made']} lookups")
    for name, number in result["requests_per_source"].items():
        print(f"  {name:6} {number:4} outbound requests")
    print(f"  {'total':6} {result['requests_total']:4}")


def is_subset(old, new):
    """True if everything in `old` is still in `new` with the same value. New extra fields in `new` are allowed."""
    if isinstance(old, dict):
        return isinstance(new, dict) and all(key in new and is_subset(value, new[key]) for key, value in old.items())
    if isinstance(old, list):
        return isinstance(new, list) and len(old) == len(new) and all(is_subset(a, b) for a, b in zip(old, new))
    return old == new


def compare():
    before = json.loads((RESULTS / "before.json").read_text())
    after = json.loads((RESULTS / "after.json").read_text())
    print_table(before)
    print_table(after)
    print("\nsaved by caching:")
    for name in before["requests_per_source"]:
        was, now = before["requests_per_source"][name], after["requests_per_source"][name]
        print(f"  {name:6} {was:4} -> {now:4}")
    print(f"  {'total':6} {before['requests_total']:4} -> {after['requests_total']:4}")

    changed = [
        old["typed"]
        for old, new in zip(before["lookups"], after["lookups"])
        if old["http_status"] != new["http_status"] or not is_subset(old["body"], new["body"])
    ]
    if changed:
        print(f"\nANSWERS CHANGED for: {changed}")
        sys.exit(1)
    print("\nevery answer is unchanged")


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else ""
    if mode == "compare":
        compare()
    elif mode in ("before", "after"):
        run(mode)
    else:
        sys.exit("usage: python bench/run_benchmark.py before|after|compare")
