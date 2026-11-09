"""MCP server for the simple IOC portal.

It is a thin client of the portal's backend API (never of the sources directly), so Claude
can ask for lookups in chat. It talks to Claude over stdio: NOTHING may be printed to stdout
except the protocol. Log to stderr only.

The backend's address comes from the BACKEND_URL environment variable (no default).
"""

import logging
import os
import sys
from urllib.parse import quote

import requests
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

logging.basicConfig(stream=sys.stderr, level=logging.INFO)
log = logging.getLogger("ioc-mcp")

# A fresh lookup runs DNS, RDAP and crt.sh one after another; crt.sh alone may take 60 s.
WAIT_SECONDS = 100
CACHE_HEADER_PREFIX = "x-cache-age-"

mcp = MCPServer("ioc-simple-dns")


def backend_url():
    """The portal backend's address, from configuration. Fails with a clear message if unset."""
    url = os.environ.get("BACKEND_URL", "").strip().rstrip("/")
    if not url:
        raise ToolError("BACKEND_URL is not set. Set it to the portal backend address, e.g. http://127.0.0.1:8010")
    return url


def get(path):
    """GET one backend path. A backend that cannot be reached becomes a tool error, never a crash."""
    url = backend_url() + path
    try:
        return requests.get(url, timeout=WAIT_SECONDS)
    except requests.ConnectionError:
        raise ToolError(f"Cannot reach the portal backend at {backend_url()}. Is it running (python -m backend.app)?")
    except requests.Timeout:
        raise ToolError(f"The portal backend did not answer within {WAIT_SECONDS} seconds.")


@mcp.tool()
def lookup_domain(name: str) -> dict:
    """Look up facts about a DNS domain name through the IOC portal.

    Input: one domain name such as "example.com" (not an IP address, URL or hash).
    Output: {"ioc": {...}, "sources": {"dns": ..., "rdap": ..., "crtsh": ...}, "assessment": {...}, "cache_age_seconds": {...}}.
    Each source answers independently with status "ok", "not_found" or "error", plus its data:
      - dns   (Google Public DNS): A, AAAA, NS, MX and TXT records with their TTLs.
      - rdap  (rdap.org, then the registry): registrar, registered/expires/last-changed dates, statuses, nameservers.
      - crtsh (crt.sh certificate transparency): certificate count, first/last seen, issuers, names on the certificates.
    Each source also has "score" (0 to 100, or null after an error) and "score_reason" (the signals that fired).
    The scale is 0 = definitely safe, 100 = definitely malware.
    "assessment" has the average score, how many sources were scored ("sources_used" of "sources_total"), the verdict
    ("verdict", "verdict_label": definitely safe, likely safe, undetermined, likely malware, definitely malware)
    and "verdict_note" (text when a "definitely" verdict was lowered because a source gave no score, else null).
    "cache_age_seconds" lists, per source, how old a cached answer is; a source missing from it was fetched fresh.
    If fewer than 2 of the 3 sources answer, the backend answers 502: the result carries an "error" message and each
    source's block, but no "assessment" and no scores.
    A fresh lookup can take up to about a minute because crt.sh is slow.

    The score and verdict are the portal's rough risk indicator from public registration facts, not a malware test.
    Report them as the portal gave them. Do not add a verdict, a score or a conclusion of your own.
    Do not look up internal or private names: the lookup is sent to outside services.
    An invalid name (IP address, URL, single label, bad characters) is returned as a tool error.
    """
    response = get("/api/v1/domain/" + quote(name.strip(), safe=""))

    if response.status_code == 400:
        message = _json(response).get("error", "not a valid DNS name")
        raise ToolError(message)
    if response.status_code not in (200, 502):
        raise ToolError(f"The portal backend answered with an unexpected status {response.status_code}.")

    body = _json(response)
    ages = {}
    for header, value in response.headers.items():
        if header.lower().startswith(CACHE_HEADER_PREFIX):
            ages[header.lower()[len(CACHE_HEADER_PREFIX):]] = value
    body["cache_age_seconds"] = ages
    return body


@mcp.tool()
def health() -> dict:
    """Check that the IOC portal backend is running and reachable. Takes no input; returns {"status": "ok"} when healthy."""
    response = get("/api/v1/health")
    if response.status_code != 200:
        raise ToolError(f"The portal backend answered health with status {response.status_code}.")
    return _json(response)


def _json(response):
    """The backend's JSON body, or a tool error if it is not JSON."""
    try:
        return response.json()
    except ValueError:
        raise ToolError("The portal backend sent an answer that is not JSON.")


def main():
    if not os.environ.get("BACKEND_URL", "").strip():
        print("BACKEND_URL is not set. Set it to the portal backend address.", file=sys.stderr)
        sys.exit(1)
    log.info("starting, backend at %s", backend_url())
    mcp.run()  # stdio


if __name__ == "__main__":
    main()
