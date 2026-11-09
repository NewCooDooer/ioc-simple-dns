"""Asks the outside sources about a name.

Every ask_... function returns a small "result" dictionary, and none of them ever crashes:
a problem is reported as an error result instead, so one failing source can never break the others.
"""

import os

import requests

from backend import cache

# The addresses of the real services. They can be changed with environment variables, only to make a source
# fail on purpose (for example CRTSH_URL=http://127.0.0.1:9/ gives "connection refused").
DNS_URL = os.environ.get("DNS_URL", "https://dns.google/resolve")
RDAP_URL = os.environ.get("RDAP_URL", "https://rdap.org")
CRTSH_URL = os.environ.get("CRTSH_URL", "https://crt.sh")

SOURCE_TIMEOUT = 10  # seconds to wait for Google DNS or RDAP before giving up
CRTSH_TIMEOUT = 60  # crt.sh is slow, so it gets much longer

# We tell every service who we are. (No personal e-mail address in it, on purpose.)
USER_AGENT = "ioc-simple-dns/0.1 (training project)"

# The kinds of DNS record we ask for, and the number DNS uses for each kind.
RECORD_TYPES = {"A": 1, "AAAA": 28, "NS": 2, "MX": 15, "TXT": 16}

# crt.sh can return thousands of names, so we only keep a sample of them.
MAX_NAMES = 50
MAX_ISSUERS = 10


# ---- three tiny helpers that build a result. Every source uses these, so every result has the same shape. ----

def ok_result(data):
    return {"status": "ok", "data": data}


def not_found_result():
    return {"status": "not_found", "data": None}


def error_result(code, message):
    return {"status": "error", "data": None, "error": {"code": code, "message": message}}


def max_age(response):
    """Read the number of seconds from a reply's 'Cache-Control: ..., max-age=300' header. None if there is none."""
    for part in response.headers.get("Cache-Control", "").split(","):
        part = part.strip().lower()
        if part.startswith("max-age="):
            try:
                return int(part[len("max-age="):])
            except ValueError:
                return None
    return None


def fetch(label, url, timeout, params=None, headers=None):
    """Send one web request.

    Returns TWO things: (response, None) if it worked, or (None, error_result) if it did not.
    Python lets a function return several values at once, and the caller can unpack them:  response, problem = fetch(...)
    """
    all_headers = {"User-Agent": USER_AGENT}
    if headers is not None:
        all_headers.update(headers)
    try:
        response = requests.get(url, params=params, headers=all_headers, timeout=timeout)
    except requests.Timeout:
        return None, error_result("timeout", f"{label} did not answer within {timeout} s")
    except requests.RequestException as problem:
        return None, error_result("upstream_error", f"could not reach {label}: {type(problem).__name__}")
    return response, None


# ---- source 1: Google DNS ----

def ask_dns(name):
    """Google DNS result for a name, from the cache if a fresh copy exists. Google's terms say we may not keep an
    answer longer than its Cache-Control header allows, so the time to keep comes from Google's replies.

    Returns TWO things: (result, age). The age is the seconds since the result was fetched if it came from the cache,
    or None if it was just fetched. (The three ask_... functions all work this way.)"""
    cached = cache.lookup("dns", name)
    if cached is not None:
        return cached
    result, keep_seconds = fetch_dns(name)
    cache.store("dns", name, result, keep_seconds)  # store() ignores errors and a time of 0
    return result, None


def fetch_dns(name):
    """Ask Google DNS for the A, AAAA, NS, MX and TXT records of a name.

    Returns TWO things: the result, and how many seconds it may be kept. That is the SHORTEST max-age of the replies
    we used; if any reply had no max-age, it is 0 (do not keep it).
    """
    data = {"resolver": "dns.google", "rcode": "NOERROR"}
    keep_seconds = None

    for record_type, number in RECORD_TYPES.items():
        response, problem = fetch("Google DNS", DNS_URL, SOURCE_TIMEOUT, params={"name": name, "type": number})
        if problem is not None:
            return problem, 0

        # The reply arrived, but it might still be a failure (HTTP status 400 or higher).
        if response.status_code != 200:
            return error_result("upstream_error", f"Google DNS returned HTTP {response.status_code}"), 0

        age = max_age(response)
        if age is None:
            keep_seconds = 0
        elif keep_seconds is None:
            keep_seconds = age
        else:
            keep_seconds = min(keep_seconds, age)

        # Read the reply. If it is not what we expect, report that instead of crashing.
        try:
            body = response.json()
            status = body["Status"]  # DNS's own status number: 0 = fine, 3 = this name does not exist
            records = []
            for item in body.get("Answer", []):
                if item.get("type") == number:  # keep only the kind of record we asked for
                    records.append({"value": item["data"], "ttl": item["TTL"]})
        except (ValueError, KeyError, TypeError, AttributeError):
            return error_result("invalid_response", "Google DNS returned a response we could not parse"), 0

        if status == 3:
            return not_found_result(), keep_seconds
        if status != 0:
            return error_result("upstream_error", f"Google DNS returned status {status}"), 0

        data[record_type] = records

    return ok_result(data), keep_seconds


# ---- source 2: RDAP (who registered the name, and when) ----

def ask_rdap(name):
    """RDAP result for a name, from the cache if a fresh copy exists. 'Not found' is kept for less time than a record."""
    cached = cache.lookup("rdap", name)
    if cached is not None:
        return cached
    result = fetch_rdap(name)
    if result["status"] == "ok":
        cache.store("rdap", name, result, cache.RDAP_OK_SECONDS)
    elif result["status"] == "not_found":
        cache.store("rdap", name, result, cache.RDAP_NOT_FOUND_SECONDS)
    return result, None  # an error is not stored (and store() would refuse it anyway)


def fetch_rdap(name):
    """Ask rdap.org for the registration record. rdap.org redirects us to the right registry; requests follows that by itself."""
    response, problem = fetch("RDAP", f"{RDAP_URL}/domain/{name}", SOURCE_TIMEOUT, headers={"Accept": "application/rdap+json"})
    if problem is not None:
        return problem

    # 404 means "no record": no such domain, a subdomain, or a top-level domain RDAP does not cover. That is an answer.
    if response.status_code == 404:
        return not_found_result()
    if response.status_code != 200:
        return error_result("upstream_error", f"RDAP returned HTTP {response.status_code}")

    try:
        data = pick_rdap_facts(response.json(), response.url)
    except (ValueError, KeyError, TypeError, IndexError, AttributeError):
        return error_result("invalid_response", "RDAP returned a response we could not parse")
    return ok_result(data)


def pick_rdap_facts(body, final_url):
    """Pick the facts we want out of RDAP's long reply."""
    # The reply lists dated events like {"eventAction": "registration", "eventDate": "1995-08-14T04:00:00Z"}.
    # Turn that list into a lookup table: {"registration": "1995-08-14...", "expiration": "...", ...}
    events = {}
    for event in body.get("events", []):
        events[event["eventAction"]] = event["eventDate"]

    # The registry's own page for this domain is the link marked "self", if there is one.
    registry_url = final_url
    for link in body.get("links", []):
        if link.get("rel") == "self":
            registry_url = link["href"]
            break

    # Name servers, lowercased and in alphabetical order.
    nameservers = []
    for server in body.get("nameservers", []):
        nameservers.append(server["ldhName"].lower())
    nameservers.sort()

    return {
        "registrar": find_registrar(body),
        "registered": events.get("registration"),
        "expires": events.get("expiration"),
        "last_changed": events.get("last changed"),
        "statuses": list(body.get("status", [])),
        "nameservers": nameservers,
        "registry_url": registry_url,
    }


def find_registrar(body):
    """Find the registrar's name. It is buried inside the "entities" list, in a contact-card ("vcard") format."""
    for entity in body.get("entities", []):
        if "registrar" in entity.get("roles", []):
            for item in entity.get("vcardArray", [None, []])[1]:
                if item[0] == "fn":  # "fn" means "formatted name"
                    return item[3]
    return None


# ---- source 3: crt.sh (which certificates were issued for the name) ----

def ask_crtsh(name):
    """crt.sh result for a name, from the cache if a fresh copy exists. crt.sh is the slowest source, so a hit saves the most."""
    cached = cache.lookup("crtsh", name)
    if cached is not None:
        return cached
    result = fetch_crtsh(name)
    if result["status"] == "ok":
        cache.store("crtsh", name, result, cache.CRTSH_OK_SECONDS)
    elif result["status"] == "not_found":
        cache.store("crtsh", name, result, cache.CRTSH_NOT_FOUND_SECONDS)
    return result, None


def fetch_crtsh(name):
    """Ask crt.sh for every certificate issued for a name, and summarize them. crt.sh is slow and often fails."""
    response, problem = fetch("crt.sh", f"{CRTSH_URL}/", CRTSH_TIMEOUT, params={"q": name, "output": "json"})
    if problem is not None:
        return problem

    if response.status_code != 200:
        return error_result("upstream_error", f"crt.sh returned HTTP {response.status_code}")

    try:
        rows = response.json()
        if not isinstance(rows, list):
            raise ValueError("expected a list")
        if len(rows) == 0:
            return not_found_result()  # crt.sh answered "no certificates"
        data = summarize_certificates(rows)
    except (ValueError, KeyError, TypeError, AttributeError):
        return error_result("invalid_response", "crt.sh returned a response we could not parse")
    return ok_result(data)


def summarize_certificates(rows):
    """Condense the raw certificate rows into a short summary.

    One certificate can appear twice (a "precertificate" and the final one share a serial number), so we count serial numbers.
    """
    # A "set" keeps each value only once, which is exactly what we want for counting and for lists of unique names.
    serials = set()
    issuers = set()
    names = set()
    start_dates = []
    for row in rows:
        serials.add(row["serial_number"])
        issuers.add(row["issuer_name"])
        start_dates.append(row["not_before"])
        # One certificate can list several names, one per line. Add each non-empty line.
        for line in row["name_value"].split("\n"):
            cleaned = line.strip()
            if cleaned != "":
                names.add(cleaned)

    sorted_names = sorted(names)
    return {
        "certificate_count": len(serials),
        "first_seen": min(start_dates),
        "last_seen": max(start_dates),
        "issuers": sorted(issuers)[:MAX_ISSUERS],
        "names": sorted_names[:MAX_NAMES],
        "names_truncated": len(sorted_names) > MAX_NAMES,
    }
