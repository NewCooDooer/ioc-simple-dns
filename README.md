# IOC Enrichment Portal (DNS names), the simple version

A deliberately **small** version of the IOC Enrichment Portal, built step by step so that every line can be explained.
It follows the same assignment specifications as the full version, with the simplest possible code: plain functions, no async, no extras.

**Status: Milestone 1 (the thinnest working slice).** One real source works end to end: Google DNS over HTTPS.
RDAP and crt.sh, and the recorded offline tests, arrive in Milestone 2. The plan, API contract and definitions of done are in [`design.md`](design.md);
the evidence for each milestone is in [`docs/milestones.md`](docs/milestones.md).

> **Do not enter internal or private names** (for example `*.corp`, `*.local`, your company's domains). Lookups go to outside services.
> The sources report facts and none of them gives a verdict.

The full, finished version (themed interface, concurrent lookups) is here: https://github.com/NewCooDooer/ioc-enrichment-portal-dns

## What it does

- A **Flask backend** (`backend/`) checks the name, asks the source, and returns one JSON answer at `GET /api/v1/domain/{name}`.
- A **Streamlit page** (`frontend/`) shows the answer. It only talks to the backend and never calls a source itself.

## Install

Requires Python 3.11 or newer (developed on 3.14). No Docker and no API keys.

```bash
git clone https://github.com/NewCooDooer/ioc-simple-dns.git
cd ioc-simple-dns
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
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

Open http://localhost:8510, type a name such as `example.com`, and press Enter.

| Setting | Default | Meaning |
|---|---|---|
| `BACKEND_PORT` | `8010` | port the backend listens on |
| `BACKEND_URL` | `http://127.0.0.1:8010` | where the page finds the backend |
| `--server.port` | (set on the command) | port the page listens on |

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
See [`design.md`](design.md) section 4 for the full contract.

## Files

```
backend/validate.py   checks and cleans the typed name
backend/sources.py    asks Google DNS (RDAP and crt.sh arrive in Milestone 2)
backend/app.py        the Flask web server and its routes
frontend/page.py      the Streamlit page
design.md             the plan and the API contract
docs/                 evidence for each milestone
```
