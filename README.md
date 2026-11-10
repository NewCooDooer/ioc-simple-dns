# IOC Enrichment Portal (DNS names), simple version

A small web page and API that shows what three public sources (Google DNS, RDAP and crt.sh) say about a
domain name, with a rough 0-100 risk score and a verdict. It is a risk indicator, not a malware test.
No API keys are needed. How it works and the API contract: [design.md](design.md).

> Do not enter internal or private names: lookups go to outside services.

## Set up

Needs Python 3 (developed on 3.14).

```bash
git clone https://github.com/NewCooDooer/ioc-simple-dns.git
cd ioc-simple-dns
python3 -m venv .venv
source .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt
```

## Run

Two terminals, both with the virtual environment active:

```bash
python -m backend.app              # terminal 1: the API
streamlit run frontend/page.py     # terminal 2: the page
```

Each prints its address. Type a name such as `example.com` on the page; crt.sh is slow, so a lookup can take
up to a minute. If a port is busy, set `BACKEND_PORT` for the backend and `BACKEND_URL` for the page.

## Test

```bash
python -m pytest
```

No network and no keys needed: the tests replay recorded real answers.

## Use it from Claude

The MCP server lets Claude Desktop call the backend: setup is in [mcp_server/README.md](mcp_server/README.md).
`.claude/skills/ioc-dns-lookup/` is a skill that formats the answers; open this folder in a Claude Code session to use it.
