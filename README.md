# IOC Enrichment Portal (DNS names), the simple version

A deliberately **small** version of the IOC Enrichment Portal, built step by step so that every line can be explained.
It follows the same assignment specifications as the full version, with the simplest possible code: plain functions, no async, no extras.

**Status: Milestone 4.** Three real, keyless sources in one answer: Google DNS over HTTPS (where the name points), RDAP (who registered it and when)
and crt.sh (which certificates were issued). If one source fails, the other two still return and the failed one says what went wrong.
Each source gets a 0-100 score, the scores are averaged, and the average gives a verdict (likely malware, undetermined or likely safe). Only when all three sources scored can the verdict be more than undetermined.
Answers are **cached in memory** (each source for its own time, see [Caching](#caching)), and the backend says which sources came from the cache (in response headers; the JSON body is unchanged).
Tests replay recorded real answers and run with the network off. The plan and the API contract are in [`design.md`](design.md);
the evidence for each milestone is in [`docs/milestones.md`](docs/milestones.md).

> **Do not enter internal or private names** (for example `*.corp`, `*.local`, your company's domains). Lookups go to outside services.
> The sources report facts; the backend turns them into a rough score and verdict, which is a guess, not a finding.

The full, finished version (themed interface, concurrent lookups) is here: https://github.com/NewCooDooer/ioc-enrichment-portal-dns

## What it does

- A **Flask backend** (`backend/`) checks the name, asks the three sources one after another, and returns one JSON answer at `GET /api/v1/domain/{name}`.
- A **Streamlit page** (`frontend/`) shows the answer. It only talks to the backend and never calls a source itself.
- Because the sources are asked one after another, a lookup takes the **sum** of their times. crt.sh alone can take up to a minute.

## Install

Requires Python 3.11 or newer (developed on 3.14). No Docker and no API keys.

```bash
git clone https://github.com/NewCooDooer/ioc-simple-dns.git
cd ioc-simple-dns
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt
```

## Run (two terminals, both with the virtual environment activated)

Terminal 1, the backend:

```bash
python -m backend.app
```

Terminal 2, the page:

```bash
streamlit run frontend/page.py --server.port 8510
```

Open http://localhost:8510, type a name such as `example.com`, and press Enter. Be patient: crt.sh is slow and often shows an error. The backend asks crt.sh a second time after a quick HTTP 5xx answer (not after a timeout).

| Setting | Default | Meaning |
|---|---|---|
| `BACKEND_PORT` | `8010` | port the backend listens on |
| `BACKEND_URL` | `http://127.0.0.1:8010` | where the page finds the backend |
| `--server.port` | (set on the command) | port the page listens on |
| `DNS_URL`, `RDAP_URL`, `CRTSH_URL` | the real services | change ONLY to make a source fail on purpose |

Both programs listen on this computer only (`127.0.0.1`). If you see "port is already in use", another program (for example another project's copy) is using that
port: stop it with `Ctrl+C` in its terminal, or pick another port, for example `BACKEND_PORT=8011 python -m backend.app` together with
`BACKEND_URL=http://127.0.0.1:8011 streamlit run frontend/page.py --server.port 8511`.

## Try the API

```bash
curl -s http://127.0.0.1:8010/api/v1/domain/example.com
curl -s http://127.0.0.1:8010/api/v1/domain/10.0.0.1     # 400 with {"error": ..., "input": ...}
curl -s http://127.0.0.1:8010/api/v1/health
```

Each source in the answer has a `status`: `ok`, `not_found` (the source answered "nothing known") or `error` (the check could not be completed).
A failing source never hides the others; only when **all** sources fail does the API answer 502. Each source also has a `score` (0 = definitely malware, 100 = definitely not malware, or `null` after an error) and the answer has an `assessment` with the average and the verdict.
See [`design.md`](design.md) sections 4 and 4a for the full contract and the scoring rules.

## Caching

Each source's result is kept in memory so that asking again does not contact the source again: Google DNS for the time Google's own `Cache-Control` header allows
(its terms require that), RDAP for 1 hour, crt.sh for 6 hours; "not found" for less (5 and 10 minutes); an **error is never kept**. The reasons are in
[`design.md`](design.md) section 11. A source that came from the cache gets a response header `X-Cache-Age-<source>: N` (N = seconds since it was fetched; no header means it was just fetched), and the page shows "Cached result, fetched 7 min ago".
The cache is emptied when the backend restarts.

### See a source fail on purpose

Point one source at an address where nothing listens (the defaults are the real services):

```bash
CRTSH_URL=http://127.0.0.1:9/ python -m backend.app
curl -s http://127.0.0.1:8010/api/v1/domain/example.com    # dns and rdap ok, crtsh {"status": "error", ...}
```

## Test

```bash
python -m pytest
```

No API key and no network needed. The tests replay real answers recorded in `tests/fixtures/` (saved by `python record.py`, which stores only the address,
status number and body, never headers). `pytest-socket` makes any real network connection fail the test. To prove it at the operating-system level on macOS:

```bash
sandbox-exec -p '(version 1)(allow default)(deny network*)' python -m pytest -v
```

The tests cover a known name, an unknown name, a real recorded crt.sh 502, all sources failing (502), invalid input (400), and two failures that are
**simulated** (a timeout and an unreadable answer), because a real service cannot be asked to fail on command.

The cache tests (`tests/test_cache.py`) show a hit, a miss, an expired entry (with a fake clock, so nothing waits) and errors that are not cached.

### Count the outbound requests (the fixed run)

```bash
python bench/run_benchmark.py before    # run on code WITHOUT the cache  -> bench/results/before.json
python bench/run_benchmark.py after     # run on code WITH the cache     -> bench/results/after.json
python bench/run_benchmark.py compare   # both tables, and a check that every answer is unchanged
```

It sends the same 27 lookups through the backend (repeats, different spellings of one name, a name that does not exist, a failing crt.sh, invalid input).
A fake web replays the recordings and sockets are blocked, so **no real request is sent and no quota is spent**. It counts the requests each source would have received.

The two files in `bench/results/` are **generated** by the commands above (about 5,000 lines of per-request output); do not edit them by hand, rerun the commands instead.

To record fresh real answers (rarely needed; crt.sh may need many retries): `python record.py`, or just one case, for example `python record.py crtsh_error`.

## Use from Claude Desktop (MCP)

`mcp_server/server.py` lets Claude call the backend as tools (`lookup_domain`, `health`). Start the backend first (`python -m backend.app`), then add this to
`claude_desktop_config.json` (use your own paths) and restart Claude Desktop:

```json
{"mcpServers": {"ioc-dns": {
  "command": "<path>\\ioc-simple-dns\\.venv\\Scripts\\python.exe",
  "args": ["<path>\\ioc-simple-dns\\mcp_server\\server.py"],
  "env": {"BACKEND_URL": "http://127.0.0.1:8010"}}}}
```

`BACKEND_URL` is required; there is no default. Then ask Claude, for example, "look up example.com". No key is needed. See `design.md` section 12 for the decisions.

If you already have other servers in the file, add `"ioc-dns": {...}` inside the existing `"mcpServers"` object (with a comma between entries); do not paste a second outer `{ }`.
If the server shows as failed, open its log, `...\AppData\Local\Claude\logs\mcp-server-ioc-dns.log` (also behind "View logs" in Claude Desktop's settings), which shows the Python error.

## Files

```
backend/validate.py   checks and cleans the typed name
backend/sources.py    asks Google DNS, RDAP and crt.sh
backend/cache.py      the in-memory cache (what is kept, for how long)
backend/app.py        the Flask web server and its routes
bench/                the fixed run that counts outbound requests
frontend/page.py      the Streamlit page
mcp_server/server.py  the MCP server that lets Claude call the backend
record.py             saves real answers for the tests (run by hand)
tests/                the tests and the recorded answers (tests/fixtures/)
design.md             the plan and the API contract
docs/                 evidence for each milestone
```
