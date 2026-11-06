# IOC Enrichment Portal (DNS names), simple version: design

Status: Milestone 0 · Written 2026-11-06 · Owner: Evan Murphy

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

**`not_found` is an answer; `error` is not.** A failed source never changes the status code. The other sources still return.
In Milestone 1 only `dns` is present; `rdap` and `crtsh` are added in Milestone 2 without renaming anything.

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

## 10. How this differs from the full version

Plain Flask and `requests` instead of FastAPI and async code; plain dictionaries instead of model classes; three small backend files instead of fifteen;
no themed interface; sources asked one after another instead of at the same time. Same contract, same three sources, same rules about facts and failures.
