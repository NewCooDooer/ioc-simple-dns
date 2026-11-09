# IOC Enrichment Portal (DNS names), simple version: design

Status: Milestone 3 (scoring) · Written 2026-11-06, updated 2026-11-09 · Owner: Evan Murphy

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
The sources report facts. From Milestone 3 the backend also turns those facts into a score and a **verdict** (section 4a). The verdict is a rough guess made from three
weak signals, **not a finding**: the page and the API must always present it that way, and it never replaces the facts underneath.

**Out of scope for this version:** async code, threads, retries, caching, a database, accounts, bulk lookups, containers, a blocking guard for private names
(a later course topic), and any theme or mascot.

## 2. Architecture

```
Browser -> Streamlit page (port 8510) --HTTP/JSON--> Flask backend (port 8010) -> Google DNS, then RDAP, then crt.sh
```

- Two separate Python programs: `backend/` and `frontend/`. The page gets **all** its data from the backend and never calls a source.
- The backend checks the name, asks the three sources **one after another** (plain functions, no concurrency), and returns one JSON answer.
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
               "A": [{ "value": "104.20.23.154", "ttl": 300 }], "AAAA": [], "NS": [], "MX": [], "TXT": [] },
               "score": 60, "score_reason": "the name resolves to an address" },
    "rdap":  { "status": "ok", "data": { "registrar": "...", "registered": "1995-08-14T04:00:00Z", "expires": "...",
               "nameservers": ["..."], "registry_url": "..." },
               "score": 90, "score_reason": "registered 5 years or more ago" },
    "crtsh": { "status": "error", "data": null,
               "error": { "code": "upstream_error", "message": "crt.sh returned HTTP 502" },
               "score": null, "score_reason": "no score: the source could not be reached" }
  },
  "assessment": { "score_min": 0, "score_max": 100, "average": 75, "sources_used": 2, "sources_total": 3,
                  "verdict": "likely_safe", "verdict_label": "Likely safe" }
}
```

Every source block has `status`, `data` and, only on error, `error`:

| status | meaning |
|---|---|
| `ok` | the source answered with data |
| `not_found` | the source answered "I know nothing about this name" |
| `error` | we could not get an answer (`error.code` is `timeout`, `upstream_error` or `invalid_response`) |

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

## 4a. Scores and verdict (Milestone 3)

After the three sources have been asked, each source's result becomes a **score from 0 to 100**: **0 = definitely malware, 100 = definitely not malware**.
The scores are rough guesses from weak signals. Each source block carries `score` (integer, or `null`) and `score_reason` (a plain sentence). Old fields are unchanged.

| Source and status | Score | Reason |
|---|---|---|
| any source, `error` | `null` (no score) | A failure says nothing about the name. The source is **left out** of the average. |
| any source, `not_found` | 50 | A real answer, but with little meaning (RDAP also says it for subdomains and for `.de` / `.io`), so it is neutral. |
| dns, `ok`, has an A or AAAA record | 60 | Resolving is weak evidence: malware names resolve too. |
| dns, `ok`, no A and no AAAA record | 40 | The name exists but points nowhere, which is slightly odd. |
| rdap, `ok`, registered under 30 days ago | 15 | Newly registered names are a classic warning sign. |
| rdap, `ok`, 30 days up to 1 year | 40 | Still young. |
| rdap, `ok`, 1 year up to 5 years | 70 | Established. |
| rdap, `ok`, 5 years or more | 90 | Long-lived names are rarely throw-away malware names. |
| rdap, `ok`, no registration date | 50 | Nothing to judge by. |
| crtsh, `ok`, first certificate under 30 days ago | 25 | A brand-new certificate history is a warning sign. |
| crtsh, `ok`, 30 days up to 1 year | 50 | Neutral. |
| crtsh, `ok`, 1 year or more | 75 | A long certificate history suggests an established site. |

"Years" are counted as 365 days. Age is measured against today's date (UTC) when the lookup runs.

**Average.** The average of the scores that exist, **rounded to a whole number** (a .5 rounds up). `sources_used` says how many scores were averaged out of `sources_total` (3).

**Verdict** (decided from the rounded average):

| Average | `verdict` | `verdict_label` |
|---|---|---|
| 0 to 40 | `likely_malware` | Likely malware |
| 41 to 60 | `undetermined` | Undetermined |
| 61 to 100 | `likely_safe` | Likely safe |

There is deliberately no "definitely" verdict: three weak signals cannot support one. (The first request named five verdicts; three were chosen with the project owner on 2026-11-09.)

**No score at all.** If no source produced a score (only possible when every source ended in `error`) the answer is the existing 502 and carries no assessment.
Otherwise at least one score exists. A `not_found` is a score of 50, so a name nobody knows lands on `undetermined`.

`assessment` fields: `score_min` (0), `score_max` (100), `average` (integer), `sources_used` (integer 1 to 3), `sources_total` (3), `verdict` (code), `verdict_label` (text).

## 5. Input rules

Trim spaces, drop one trailing dot, lowercase. Reject: empty input; IP addresses; `/ : @ ? #` and spaces; names over 253 characters; a single word like
`localhost`; any label that is empty, longer than 63, starts or ends with `-`, or has characters other than `a-z 0-9 - _`; a last label that is all digits.
Non-English letters become punycode (`bücher.de` becomes `xn--bcher-kva.de`). The answer shows both what was typed and the cleaned name.

## 6. Data sources (checked on the providers' own pages, 2026-11-06; earlier check 2026-11-05)

| Source | Key | Limit | Terms and notes |
|---|---|---|---|
| **Google Public DNS** `https://dns.google/resolve` ([docs](https://developers.google.com/speed/public-dns/docs/doh/json)) | no | Default **1500 queries/s per client IP** with short bursts allowed ([ISP page](https://developers.google.com/speed/public-dns/docs/isp)); its [troubleshooting page](https://developers.google.com/speed/public-dns/docs/troubleshooting) says 1000. Neither mentions DNS over HTTPS specifically. | Free, **no SLA**. Google logs the queried name and your IP for 24 to 48 hours ([privacy](https://developers.google.com/speed/public-dns/privacy)). |
| **RDAP** `https://rdap.org/domain/{name}` ([about](https://about.rdap.org/)) | no | **10 requests per 10 s**, then 429 | 302 redirects to the registry (must be followed); 404 = unknown, or a top-level domain it does not cover (for example `.de`, `.io`); 403 = blocked for abuse. No formal terms. |
| **crt.sh** `https://crt.sh/?q={name}&output=json` | no | None published | No official terms found. Run by Sectigo. Unreliable: it often answers HTTP 502 and can take up to a minute (it timed out at 45 s on 2026-11-06). |

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

**Milestone 3: scores and verdict.** Done when:
1. Every source block has `score` and `score_reason`; the response has `assessment` as in section 4a; no old field changed.
2. The average, the three verdicts and their band edges (40/41, 60/61) are tested, as are each source's scoring, a failing source and the all-failed case.
3. The page shows the three scores, the average, the verdict and the caveat.
4. `design.md` and the README match the code; merged to `main` through a pull request.

## 10. How this differs from the full version

Plain Flask and `requests` instead of FastAPI and async code; plain dictionaries instead of model classes; three small backend files instead of fifteen;
no themed interface; sources asked one after another instead of at the same time. Same contract, same three sources, same rules about facts and failures.
