# IOC Enrichment Portal (DNS names), simple version: design

Status: Milestone 3 (caching) · Written 2026-11-06, updated for Milestone 3 · Owner: Evan Murphy

This is a deliberately **small** version of an existing, finished project (https://github.com/NewCooDooer/ioc-enrichment-portal-dns).
It meets the same assignment specs with the simplest code possible: plain functions, no `async`, no extras.
Read this file before changing the API or adding a feature.

## 1. Goal and scope

A SOC analyst types a **DNS name** into a web page and sees what three real, keyless public sources say about it:

| Question | Source |
|---|---|
| Where does the name point? | Google Public DNS over HTTPS |
| Who registered it, and when? | RDAP (rdap.org) |
| Which TLS certificates were issued for it? | crt.sh (Certificate Transparency) |

Other programs may call the backend later, so **the API contract (section 4) is the product** and the web page is one client of it.
The sources report facts. Nothing in this project may call a name "safe" or "malicious".

**Out of scope for this version:** async code, threads, retries, a database, accounts, bulk lookups, containers, a blocking guard for private names
(a later course topic), and any theme or mascot.

## 2. Architecture

```
Browser -> Streamlit page (port 8510) --HTTP/JSON--> Flask backend (port 8010) -> Google DNS, then RDAP, then crt.sh
```

- Two separate Python programs: `backend/` and `frontend/`. The page gets **all** its data from the backend and never calls a source.
- The backend checks the name, asks the three sources **one after another** (plain functions, no concurrency), and returns one JSON answer.
- Before asking a source, the backend looks in a small in-memory cache (section 11). A fresh copy is returned without any outbound request.
- Cost of that simplicity: a lookup takes the **sum** of the three sources. crt.sh alone can take up to a minute, so the page shows a "please wait" message.
- Ports: backend `BACKEND_PORT` (default 8010); the page finds the backend with `BACKEND_URL` (default `http://127.0.0.1:8010`) and runs on `--server.port` (8510).
  Both programs listen on `127.0.0.1` only.

## 3. Stack and decisions (with reasons)

| Decision | Choice | Reason / what would change it |
|---|---|---|
| Backend | **Flask** | The simplest Python web framework; ordinary functions, no async. |
| HTTP client | **requests** | Plain, well known, synchronous. |
| Frontend | **Streamlit** | A whole page in a few lines of Python. |
| Data | plain dictionaries | No model classes to learn; the contract is documented here and checked by tests. |
| Tests (Milestone 2) | **pytest + responses + pytest-socket** | `responses` replays recorded answers through `requests`; `pytest-socket` makes any real network call fail. |
| Recordings | JSON files saved by `record.py` | Readable; the recorder saves status and body only, never headers, so no key can leak. |
| Settings | environment variables | `BACKEND_PORT`, `BACKEND_URL`, plus three optional source addresses (only to make a source fail on purpose). |
| Cache (Milestone 3) | a plain dictionary in memory, guarded by a lock | No new dependency and no database. Lost on restart, which is acceptable for a cache (section 11). |
| Containers | none | Allowed (at most two); fewer moving parts. |
| Identification | a `User-Agent` header saying `ioc-simple-dns/0.1 (training project)` | Polite to public services. It deliberately contains no personal e-mail address. |
| Python | 3.11 or newer (developed on 3.14.7) | |
| Repository | public | The instructor must be able to read it; there are no keys. |

## 4. API contract (version 1)

Base path `/api/v1`, JSON everywhere. A breaking change would go to `/api/v2/`.

`GET /api/v1/domain/{name}` returns **200** when the name is valid and at least one source answered (`ok` or `not_found`):

```json
{
  "ioc": { "type": "domain", "input": "Example.com", "value": "example.com" },
  "sources": {
    "dns":   { "status": "ok", "data": { "resolver": "dns.google", "rcode": "NOERROR",
               "A": [{ "value": "104.20.23.154", "ttl": 300 }], "AAAA": [], "NS": [], "MX": [], "TXT": [] } },
    "rdap":  { "status": "ok", "data": { "registrar": "...", "registered": "1995-08-14T04:00:00Z", "expires": "...",
               "nameservers": ["..."], "registry_url": "..." } },
    "crtsh": { "status": "error", "data": null,
               "error": { "code": "upstream_error", "message": "crt.sh returned HTTP 502" } }
  }
}
```

Every source block has `status`, `data` and, only on error, `error`:

| status | meaning |
|---|---|
| `ok` | the source answered with data |
| `not_found` | the source answered "I know nothing about this name" |
| `error` | we could not get an answer (`error.code` is `timeout`, `upstream_error` or `invalid_response`) |

**Added in Milestone 3: response headers, and no new body fields.** The JSON body is exactly as in Milestone 2. A source that came from the cache is reported in a header on the 200 response:

| Header | Meaning |
|---|---|
| `X-Cache-Age-dns`, `X-Cache-Age-rdap`, `X-Cache-Age-crtsh` | present only when that source's result came from the cache; the value is the number of seconds since it was fetched |

A source with no such header was just fetched. Example: `X-Cache-Age-rdap: 412` means the `rdap` block is a copy fetched 412 s ago. An error is never cached, so an error block never has a header, and the 502 response never has any.
The `ttl` numbers inside DNS records are Google's values at fetch time; they are **not** counted down, so use the header's age. Why a header and not a field: section 11.

**`not_found` is an answer; `error` is not.** A failed source never changes the status code. The other sources still return.
In Milestone 1 only `dns` was present; Milestone 2 adds `rdap` and `crtsh` without renaming anything. The sources are asked in the order dns, rdap, crtsh.

Other responses, always in the same format `{"error": "...", "input": "..."}` (`input` only when there is one):

| Status | When |
|---|---|
| 400 | the name is not a valid DNS name (an IP address, a URL, spaces, ...) |
| 502 | **all** sources ended in `error` |
| 404 | unknown address (including an empty name) |
| 500 | an unexpected bug (details go to the log, not the answer) |

`GET /api/v1/health` returns `{"status": "ok"}`.

## 5. Input rules

Trim spaces, drop one trailing dot, lowercase. Reject: empty input; IP addresses; `/ : @ ? #` and spaces; names over 253 characters; a single word like
`localhost`; any label that is empty, longer than 63, starts or ends with `-`, or has characters other than `a-z 0-9 - _`; a last label that is all digits.
Non-English letters become punycode (`bücher.de` becomes `xn--bcher-kva.de`). The answer shows both what was typed and the cleaned name.

## 6. Data sources (checked on the providers' own pages, 2026-11-06; earlier check 2026-11-05)

| Source | Key | Limit | Terms and notes |
|---|---|---|---|
| **Google Public DNS** `https://dns.google/resolve` ([docs](https://developers.google.com/speed/public-dns/docs/doh/json)) | no | Default **1500 queries/s per client IP** with short bursts allowed ([ISP page](https://developers.google.com/speed/public-dns/docs/isp)); its [troubleshooting page](https://developers.google.com/speed/public-dns/docs/troubleshooting) says 1000. Neither mentions DNS over HTTPS specifically. | Free, **no SLA**. Google logs the queried name and your IP for 24 to 48 hours ([privacy](https://developers.google.com/speed/public-dns/privacy)). **Caching:** the [Google APIs Terms](https://developers.google.com/terms) (section 5e) forbid keeping cached copies "longer than permitted by the cache header". |
| **RDAP** `https://rdap.org/domain/{name}` ([about](https://about.rdap.org/)) | no | **10 requests per 10 s**, then 429 | 302 redirects to the registry (must be followed); 404 = unknown, or a top-level domain it does not cover (for example `.de`, `.io`); 403 = blocked for abuse. No formal terms and nothing about caching (its 302 reply is marked `public, max-age=28800`). |
| **crt.sh** `https://crt.sh/?q={name}&output=json` | no | None on its own pages. The operator said in 2020 that requests are throttled at **60 per IP per minute** ([post](https://groups.google.com/g/crtsh/c/NZJntKrBdmg)); a later report of 5 per minute is unverified. | No official terms found. Run by Sectigo. Unreliable: it often answers HTTP 502 and can take up to a minute (it timed out at 45 s on 2026-11-06). |

Timeouts: Google and RDAP 10 s, crt.sh 60 s; the page waits up to 100 s. Lookups are **not private**: every name typed is sent to these outside services.

## 7. Tests (Milestone 2)

- `record.py` calls each real source once and saves **status and body only** into `tests/fixtures/`.
- Tests replay those files through `requests` with `responses`; `pytest-socket` makes any real network connection fail. Proof: the suite also passes under an
  operating-system network block.
- Cases: a **hit**, an **unknown** name, a **source error** (a real recorded crt.sh 502), all sources failing (502), invalid input (400), and a **simulated** timeout
  (labelled as simulated, since a real service cannot be asked to time out).

## 8. Secrets and values that must never leave the machine

There are no API keys (all sources are keyless). If one is ever added it lives in `.env` or an environment variable, never in code or recordings; `.env` is ignored by Git.
Never send to an outside service: private addresses (RFC 1918: 10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16), internal host names and domains, hashes of internal files.
This version only *documents* the rule (users are warned); enforcing it in code is a later course topic. Never upload files to VirusTotal.

## 9. Milestones

**Milestone 0: design.** Done when this file covers the eight required topics and is merged to `main` through a pull request.

**Milestone 1: thinnest slice (Google DNS only).** Done when:
1. `GET /api/v1/domain/example.com` returns `ioc` and a `dns` block as in the contract.
2. An invalid name (for example `10.0.0.1`) returns 400 with the error format, no crash.
3. The Streamlit page shows the result for a typed name, using only the backend.
4. The README explains how to install and run both parts.
5. No key or token is in any commit.
6. Merged to `main` through a pull request.

**Milestone 2: three sources and recorded tests.** Done when:
1. One response holds `dns`, `rdap` and `crtsh` results.
2. A failing source still returns the other two with its error shown; all three failing returns 502.
3. Tests replay recordings and pass with the network off, covering a hit, an unknown name and a source error.
4. No key in any recording or commit.
5. `design.md` and the README match the code.
6. Merged to `main` through a pull request.

**Milestone 3: caching.** Done when:
1. Each source has its own expiry, with the reason written in section 11, and Google DNS follows its `Cache-Control` header.
2. An error is never cached; "not found" is, for less time.
3. One IOC typed differently shares one entry; two IOCs never do; the key holds the source and never a secret.
4. A user can tell a cached result from a fresh one (the `X-Cache-Age-<source>` headers), and the body does not change; the headers are documented in section 4.
5. The existing tests keep their checks and pass; new tests show a hit, a miss, an expiry and an uncached error, all with the network off.
6. A fixed run of at least 20 lookups is counted before and after, per source, without real network access.
7. Merged to `main` through a pull request that the owner reviews.

## 10. How this differs from the full version

Plain Flask and `requests` instead of FastAPI and async code; plain dictionaries instead of model classes; three small backend files instead of fifteen;
no themed interface; sources asked one after another instead of at the same time. Same contract, same three sources, same rules about facts and failures.

## 11. Caching (Milestone 3)

**Why.** One lookup of a known name costs **8 outbound requests**: 5 to Google DNS (one per record type), 2 to RDAP (rdap.org redirects to the registry) and 1 to crt.sh.
RDAP allows only 10 requests per 10 s, crt.sh is slow, throttled and often fails, and an analyst often looks up the same IOC more than once.

**What is cached.** Each source's `ok` and `not_found` result, separately, so one failing source never discards the others' answers.
The store is `backend/cache.py`; the `ask_...` functions in `backend/sources.py` look in it first and only call the source on a miss.

**Expiry per source** (sources checked on their own pages and, for headers, with one real request each on 2026-11-06):

| Source | `ok` kept for | `not_found` kept for | Reasons: how often the data changes, how fresh an analyst needs it, how tight the limits are |
|---|---|---|---|
| Google DNS | the **smallest `max-age`** of the 5 replies (300 s seen for `example.com`) | the reply's `max-age` (900 s seen) | **Terms decide:** Google APIs Terms section 5e forbid keeping copies longer than the cache header allows. Google's header follows the record's own TTL, so DNS data is never kept past the time its owner declared. Limits are generous (about 1500 queries/s), so freshness, not quota, is what matters. A reply with **no** `max-age` is not kept at all (expiry 0): without the header there is no permission to keep it. Google sends `private`, which forbids shared proxies; this backend is Google's single client, not a proxy, so it may keep the answer for `max-age`. |
| RDAP | **1 hour** | **5 minutes** | Registrar, expiry date and name servers change over days or months, so an hour costs little accuracy, and the limit (10 requests per 10 s, then 429) is tight. "Not found" is kept briefly because a name can be registered at any moment and newly registered names are what analysts look for. No terms or caching rules exist on rdap.org's pages. |
| crt.sh | **6 hours** | **10 minutes** | Certificate history only grows, so an old answer is incomplete, never wrong. crt.sh is the slowest source (up to 60 s), is throttled per IP and often answers 502, so a hit saves the most. "Not found" is short because a new name usually gets its first certificate soon. No terms exist on its pages. |
| any source, `error` | **never** | | A timeout, a 429, a 5xx or an unreadable answer is not an answer (below). |

No source rules caching out, so no source has an expiry of zero, except Google replies that lack a `max-age`.

**Never cache an error.** `cache.store()` itself refuses any result whose status is `error`, so a slip in one source's code cannot cache a timeout, a 429 or a 502.
(A "missing key" error cannot happen in this version, since no source uses a key; it would be an `error` and so not cached.) "Not found" is an answer and is cached, for the shorter times above.

**The key** is `(source, clean name)`. The name is the output of `check_name`: trimmed, one trailing dot dropped, lowercased, punycode. So `Example.COM`, ` example.com ` and `example.com.`
share one entry, and two different names never do. It contains only the source's label and the name, never a secret.
This version supports only DNS names (IP addresses, hashes and URLs are rejected with 400), so case, spaces and the trailing dot are the spellings that matter.

**Storage.** A dictionary in memory with a lock (the Flask development server answers several requests at once). Reasons: simplest possible, no new dependency, no database (a hard constraint).
Costs: it is emptied when the backend restarts and is not shared between two backend processes. It holds at most 5000 entries (expired ones are dropped first, then the oldest).

**Telling cached from fresh.** The backend sends an `X-Cache-Age-<source>` header for each cached source (section 4), and the page prints "Cached result, fetched 7 min ago. It may have changed since."
The news goes in headers, not in the body, so the body (the product) keeps exactly its Milestone 2 shape. The cost: a client that reads only the body cannot see that a result is cached.
Why the expiry alone is not enough: results can be kept for up to 6 hours, and a cached "clean" or "not found" can be wrong an hour later (the name gets registered or gets a certificate).
An analyst deciding something from the result must be able to see how old it is.

**What did not change.** The body, every existing field, status code and the order of the sources. Invalid input still returns 400 before the cache or any source is touched.
The 502 response has no cache headers, because an error is never cached.

**Measured.** `bench/run_benchmark.py` sends the same 27 lookups (repeats, six spellings of one name, a name that does not exist, a name whose crt.sh lookup fails, two invalid inputs)
through the backend with a fake web that replays the recordings (no real requests, sockets blocked) and counts outbound requests per source:

| Source | Without cache | With cache |
|---|---|---|
| Google DNS | 109 | 26 |
| RDAP (redirect hop included) | 50 | 12 |
| crt.sh | 25 | 8 |
| **Total** | **184** | **46** |

The run does not move time, so expiry is shown by the tests in `tests/test_cache.py` (a fake clock), not by the run.
