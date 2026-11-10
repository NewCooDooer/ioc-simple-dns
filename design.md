# IOC Enrichment Portal (DNS names), simple version: design

This file holds the API contract, the data sources, the main decisions with their reasons, and the milestones. Numbers from the code (points, bands, times) are in the code, not here.
The history and the evidence of each change are in its pull request.

## Purpose and scope

A SOC analyst types a **DNS name** and sees what three keyless public sources say about it: Google Public DNS (where it points), RDAP (who registered it, and when) and crt.sh (which certificates were issued).
Other programs may call the backend, so **the API contract below is the product** and the web page is one client of it.
The backend also turns the facts into a score and a verdict. That verdict is a rough guess from public registration facts, **not a finding and not a malware test**: it cannot see reputation or blocklists, so an old name that was taken over can still look safe.
Everywhere it is shown it must be presented that way, and it never replaces the facts underneath.

Out of scope: async code, concurrent lookups, a database, accounts, bulk lookups, containers, and blocking private names in code (they are only warned about).

## Architecture

```
Browser -> Streamlit page --HTTP/JSON--> Flask backend -> Google DNS, then RDAP, then crt.sh      (a cache sits in front of each source)
```

- The page gets all its data from the backend and never calls a source. Both programs listen on `127.0.0.1` only.
- The sources are asked one after another, so a lookup takes the sum of their times (crt.sh alone can take about a minute).
- The MCP server (`mcp_server/`) and the Claude skill (`.claude/skills/`) are further clients of the backend.

## API contract (version 1)

Base path `/api/v1`, JSON everywhere. A breaking change would go to `/api/v2`.

`GET /api/v1/domain/{name}` returns **200** for any valid name:

```json
{
  "ioc": { "type": "domain", "input": "Example.com", "value": "example.com" },
  "sources": {
    "dns":   { "status": "ok", "data": { "resolver": "dns.google", "rcode": "NOERROR",
               "A": [{ "value": "104.20.23.154", "ttl": 300 }], "AAAA": [], "NS": [], "MX": [], "TXT": [] },
               "score": 40, "score_reason": "resolves to an address (-10)" },
    "rdap":  { "status": "ok", "data": { "registrar": "...", "registered": "1995-08-14T04:00:00Z", "expires": "...", "last_changed": "...",
               "statuses": ["..."], "nameservers": ["..."], "registry_url": "..." },
               "score": 10, "score_reason": "registered 5 years or more ago (-40)" },
    "crtsh": { "status": "error", "data": null,
               "error": { "code": "upstream_error", "message": "crt.sh returned HTTP 502" },
               "score": null, "score_reason": "no score: the source could not be reached, so it is left out of the average" }
  },
  "assessment": { "score_min": 0, "score_max": 100, "average": 25, "sources_used": 2, "sources_total": 3,
                  "verdict": "likely_safe", "verdict_label": "Likely safe", "verdict_note": "only 2 of 3 sources gave a score, so the verdict cannot be 'definitely'" }
}
```

- **Source `status`:** `ok` (data), `not_found` (the source answered "nothing known") or `error` (no answer; `error.code` is `timeout`, `upstream_error` or `invalid_response`). `data` is `null` unless `ok`.
- **Score:** `score` is 0 to 100, **0 = definitely safe, 100 = definitely malware**, or `null` after an error. `score_reason` lists the signals that fired.
- **Verdict:** `average` is the mean of the scores that exist, rounded to a whole number. `verdict` is one of `definitely_safe`, `likely_safe`, `undetermined`, `likely_malware`, `definitely_malware` or `not_graded`; `verdict_label` is the same in words.
  "Definitely" needs all three sources: with fewer, it is lowered to "likely" and `verdict_note` says why (otherwise `null`).
- **Nothing to grade:** if all three sources failed, the answer is still 200, every `score` is `null`, and `assessment` has `verdict` `not_graded`, `average` `null` and `sources_used` 0.

Other responses use one format, `{"error": "...", "input": "..."}` (`input` only when there is one):

| Status | When |
|---|---|
| 400 | the name is not a valid DNS name (an IP address, a URL, spaces, ...); no source is called |
| 404 | unknown address (including an empty name) |
| 405 | the HTTP method is not allowed (only `GET` works) |
| 500 | an unexpected bug (details go to the log, not the answer) |

A failing source never gives a 5xx: that is data in its own block, not a failed request.

**Cache headers.** A source block that came from the cache is reported in the response header `X-Cache-Age-<source>` (seconds since it was fetched); no header means it was just fetched. The body does not change.

`GET /api/v1/health` returns `{"status": "ok"}`.

## Data sources

All three need no key. The limits and terms are the providers' own figures, checked on their pages on 2026-11-10.

| Source | Limit | Terms and notes |
|---|---|---|
| Google Public DNS (`dns.google/resolve`) | 1500 queries per second per client address; short bursts are allowed | Its terms (Google APIs Terms, 5(e)(1)) forbid keeping cached copies longer than the cache header permits. |
| RDAP (`rdap.org`) | 10 requests in 10 seconds, then HTTP 429 | It redirects to the registry, and the redirect must be followed. A 404 means it knows no registry for that name (it only knows servers registered with IANA); a 403 means blocked for abuse. No formal terms and no caching rules. |
| crt.sh (`crt.sh`) | none published | No terms or limits on its own pages (its footer names Sectigo). In practice it is slow and often fails with an HTTP 5xx. |

## Main decisions

- **Flask, `requests`, Streamlit, plain dictionaries:** the simplest tools that do the job; the contract is checked by tests instead of model classes.
- **Sources one after another, no concurrency:** keeps the code easy to read, at the cost of a slower lookup.
- **One failing source never hides the others, and a valid name always gets a 200:** a failure is information about a source, not a failure of the request.
- **One answering source is enough to grade:** the verdict says how many sources it rests on, and "definitely" is withheld unless all three answered.
- **A score starts at 50 and signals add or subtract points:** each point has a stated reason in `backend/signals.py`, so a verdict is explainable and the points can be tuned.
- **"Definitely safe" means old, established and consistent, not proven harmless:** there is no strong sign of safety, only the absence of warning signs.
- **"Not found" is an answer and gets a score; an error does not:** a failure says nothing about the name, so that source is left out of the average.
- **Errors are never cached, and RDAP and crt.sh keep "not found" for less time than a hit:** a failure is not an answer, and a new name can be registered or get a certificate at any moment.
- **The cache key is the source plus the cleaned name** (trimmed, lowercased, punycode), so every spelling of one name shares an entry and nothing secret is in the key.
- **Google DNS is kept only as long as its own `Cache-Control` header allows:** Google's terms forbid longer, and a reply with no header is not kept at all. The other expiry times and their reasons are in `backend/cache.py`.
- **Cache age goes in headers, not in the body:** the body stays the product, and an analyst can still see how old a result is.
- **crt.sh is asked a second time after a quick HTTP 5xx, never after a timeout:** it often fails at once and works a moment later, but a second long wait would pass the page's limit.
- **No API keys:** all three sources are keyless. If one is ever added it lives in the environment, never in code or recordings.
- **Names are sent to outside services, so internal names must not be typed:** the page warns about it; blocking them in code is out of scope.
- **Tests replay recorded real answers with the network blocked:** a real service cannot be asked to fail on command, so timeouts and unreadable answers are simulated and labelled as such.
- **The MCP server calls the backend API only, never a source:** the backend stays the one place that knows the sources and the failure rules. It takes the backend address from `BACKEND_URL` (no default in code), prints nothing but the protocol to stdout, and is started by its file path because Claude Desktop ignored a working directory.
- **The Claude skill only formats what the tool returns:** the score and verdict are the portal's, never its own.

## Milestones

Each is done when its pull request is merged; the PR holds the evidence and the details.

- **M0 Design (#1):** this file covers the required topics.
- **M1 Thinnest slice (#2):** the API answers for one source (Google DNS), an invalid name gets a 400, and the page shows the result.
- **M2 Three sources and recorded tests (#3):** one answer holds all three sources, a failing source never hides the others, and the tests pass with the network off.
- **M3 Scores and verdict (#10, reworked in #13):** every source has a score and the answer has a verdict, with every rule covered by tests.
- **M4 Caching (#7):** each source is cached for its own time, errors are never cached, and the cache age is visible.
- **M5 Failure handling (#14, #16):** one answering source is enough to grade, and a failing source never gives a 5xx.
- **M6 MCP server (#8):** Claude Desktop can look up a name through a tool that calls only the backend, with offline tests.
- **M7 Claude skill (#15):** a skill makes Claude's answers follow one fixed layout and report the portal's own score and verdict.
