"""Asks the outside sources about a name.

Every function here returns a small "result" dictionary, and none of them ever crashes:
a problem is reported as an error result instead, so one failing source can never break the others.
"""

import os

import requests

# The address of the real service. It can be changed with an environment variable, only to make a source
# fail on purpose (for example DNS_URL=http://127.0.0.1:9/ gives "connection refused").
DNS_URL = os.environ.get("DNS_URL", "https://dns.google/resolve")

SOURCE_TIMEOUT = 10  # seconds to wait for an answer before giving up

# The kinds of DNS record we ask for, and the number DNS uses for each kind.
RECORD_TYPES = {"A": 1, "AAAA": 28, "NS": 2, "MX": 15, "TXT": 16}


# ---- three tiny helpers that build a result. Every source uses these, so every result has the same shape. ----

def ok_result(data):
    return {"status": "ok", "data": data}


def not_found_result():
    return {"status": "not_found", "data": None}


def error_result(code, message):
    return {"status": "error", "data": None, "error": {"code": code, "message": message}}


# ---- source 1: Google DNS ----

def ask_dns(name):
    """Ask Google DNS for the A, AAAA, NS, MX and TXT records of a name."""
    data = {"resolver": "dns.google", "rcode": "NOERROR"}

    for record_type, number in RECORD_TYPES.items():
        # Send the question. This can fail in several ways, so it is wrapped in try/except.
        try:
            response = requests.get(DNS_URL, params={"name": name, "type": number}, timeout=SOURCE_TIMEOUT)
        except requests.Timeout:
            return error_result("timeout", f"Google DNS did not answer within {SOURCE_TIMEOUT} s")
        except requests.RequestException as problem:
            return error_result("upstream_error", f"could not reach Google DNS: {type(problem).__name__}")

        # The reply arrived, but it might still be a failure (HTTP status 400 or higher).
        if response.status_code != 200:
            return error_result("upstream_error", f"Google DNS returned HTTP {response.status_code}")

        # Read the reply. If it is not what we expect, report that instead of crashing.
        try:
            body = response.json()
            status = body["Status"]  # DNS's own status number: 0 = fine, 3 = this name does not exist
            records = []
            for item in body.get("Answer", []):
                if item.get("type") == number:  # keep only the kind of record we asked for
                    records.append({"value": item["data"], "ttl": item["TTL"]})
        except (ValueError, KeyError, TypeError, AttributeError):
            return error_result("invalid_response", "Google DNS returned a response we could not parse")

        if status == 3:
            return not_found_result()
        if status != 0:
            return error_result("upstream_error", f"Google DNS returned status {status}")

        data[record_type] = records

    return ok_result(data)
