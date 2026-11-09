---
name: ioc-dns-lookup
description: Look up domain names with the ioc-dns MCP tools and report DNS, RDAP and crt.sh facts in a fixed layout. Use when the user gives a domain to look up or enrich. Facts only, no verdicts.
---

# IOC DNS lookup

## Tools (the only source)
Use only the `ioc-dns` MCP server's tools: `lookup_domain` and `health`.
Do not use web search, other MCP servers, shell commands (dig, whois, curl) or memory
to add or fill in any value. If a value is not in the tool result, write "not returned".

## What to look up
- Look up only the domain names the user typed. One `lookup_domain` call per name, exactly as given.
- Never look up anything you derived: no subdomains, `www.` variants, parent domains,
  or names found in certificates or DNS records. You may list them as text; do not look them up.
- Pass the user's text unchanged. Do not extract a domain from a URL or e-mail,
  or turn an IP address into a name. The tool decides what is valid.
- If the name looks internal or private (`.local`, `.corp`, `.internal`, a company-internal domain),
  do not call the tool. Say lookups go to outside services and ask for confirmation.
- A fresh lookup can take about a minute (crt.sh is slow). Do not retry on your own.

## Output (identical on every run)
For each name, produce exactly these sections in this order, with these headings and columns.
Never skip a section. If a section has no data, write the reason on one line (see Failures).

### <name as given>
**Lookup:** <n> ok, <n> not_found, <n> error · Cache: dns <age in seconds or fresh>, rdap <age or fresh>, crtsh <age or fresh>

#### Source status
| Source | Status | Detail |
|---|---|---|
| dns | ok / not_found / error | `<code>: <message>` if error, else - |
| rdap | ok / not_found / error | same |
| crtsh | ok / not_found / error | same |

#### DNS records
| Type | Value | TTL |
|---|---|---|

One row per record, in the order A, AAAA, NS, MX, TXT.

#### Registration (RDAP)
| Field | Value |
|---|---|
| Registrar | |
| Registered | |
| Expires | |
| Last changed | |
| Statuses | |
| Nameservers | |

#### Certificates (crt.sh)
| Field | Value |
|---|---|
| Certificate count | |
| First seen | |
| Last seen | |
| Issuers | |
| Names | add "(truncated, first 50 shown)" when `names_truncated` is true |

End each name with exactly this line: "Facts from public sources, not a verdict."
Do not call a name safe, malicious, suspicious or legitimate. Do not add risk scores or recommendations.
Copy values as returned: dates unchanged, TTLs in seconds. Do not summarise, round or reorder them.
If the user gave several names, repeat the whole block per name, in the order given.

## Failures
- A source has `status: error`: keep its row in Source status, and in its own section write
  "Not retrieved: <source> failed (<code>)." The other sources are still reported in full.
- A source has `status: not_found`: in its section write "No record: <source> has nothing for this name."
  This is an answer, not a failure.
- All three sources failed: report all three details and add "No source answered."
- The tool refuses the value (IP address, URL, single word, bad characters, empty):
  write only "Not looked up: <value as given>: <the tool's error message>" and ask for a plain domain name.
  Do not fix the value and try again.
- The tool says it cannot reach the backend or that `BACKEND_URL` is not set: call `health` once,
  report its result or error as returned, and tell the user to start the backend (`python -m backend.app`).
  Report no lookup data.
- Never fill a gap from other tools or from what you know about the domain.
