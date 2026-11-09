---
name: ioc-dns-lookup
description: Look up domain names with the ioc-dns MCP tools and report DNS, RDAP and crt.sh facts plus the portal's 0-100 score and verdict in a fixed layout. Use when the user gives a domain to look up.
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

## Scores and verdict (the portal's, not yours)
- Report `score`, `score_reason`, `assessment` and the verdict exactly as the tool returned them.
  Never compute, adjust, round, re-rank or add a score or verdict of your own, and never add advice
  (block it, it is safe to open, and so on).
- The scale is **0 = definitely safe, 100 = definitely malware**. State this under every Assessment.
  A high number means more risk, not more safety.
- The verdict is a rough risk indicator from public registration facts (name age, odd addresses,
  certificate history). It is not a malware test and cannot see blocklists or reputation.
  "Definitely safe" means old and consistent, not proven harmless.

## Output (identical on every run)
Every answer has two parts, in this order: one Summary table, then one detail block per name.
Use these headings and columns exactly. Never skip a section. If a section has no data, write the reason on one line (see Failures).

### Summary
One row per name the user gave, in the order given, even when there is only one name.
| Name | Score | Verdict | Reasons |
|---|---|---|---|
| <name as given> | <average> | <verdict_label> | dns: <score_reason>; rdap: <score_reason>; crtsh: <score_reason> |

- Score is the `average` from `assessment`, a number from 0 to 100 (0 = definitely safe, 100 = definitely malware).
- Reasons lists each source in the order dns, rdap, crtsh with its `score_reason` copied as returned.
  For a source with an error write `dns: no score (<code>)`. If `verdict_note` is not null, add `Note: <verdict_note>` at the end.
- A name with no score takes `-` in Score. Verdict and Reasons then follow the Failures section.
- Under the table write once: "Scale: 0 = definitely safe, 100 = definitely malware. A rough risk indicator from public facts, not a malware test."

Then, for each name in the same order, the detail block:

### <name as given>
**Lookup:** value `<ioc.value>` · <n> ok, <n> not_found, <n> error · Cache: dns <age in seconds or fresh>, rdap <age or fresh>, crtsh <age or fresh>

#### Assessment
| Field | Value |
|---|---|
| Average score | <average> of 100 |
| Verdict | <verdict_label> |
| Sources scored | <sources_used> of <sources_total> |
| Note | <verdict_note, or -> |

Scale: 0 = definitely safe, 100 = definitely malware. A rough risk indicator from public facts, not a malware test.

#### Source status
| Source | Status | Score | Reason or error |
|---|---|---|---|
| dns | ok / not_found / error | <score, or "no score"> | <score_reason>, or `<code>: <message>` if error |
| rdap | same | same | same |
| crtsh | same | same | same |

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

Copy values as returned: dates unchanged, TTLs in seconds. Do not summarise, round or reorder them.
If the user gave several names, repeat the whole block per name, in the order given.

## Failures
- A source has `status: error`: keep its row in Source status (Score "no score"), and in its own section write
  "Not retrieved: <source> failed (<code>)." The other sources are still reported in full.
- A source has `status: not_found`: in its section write "No record: <source> has nothing for this name."
  This is an answer, not a failure, and it has a score.
- Two or three sources failed (the tool returns an `error` such as "too few sources answered", with no `assessment`):
  in the Summary row write Score `-`, Verdict "Not graded", Reasons the error message as returned.
  In the detail block write "Not graded: fewer than 2 of 3 sources answered." under Assessment,
  and fill Source status and the data sections from the source blocks that did answer.
- The tool refuses the value (IP address, URL, single word, bad characters, empty):
  in the Summary row write Score `-`, Verdict "Not looked up", Reasons the tool's error message as returned.
  Give that name no detail block. Ask for a plain domain name. Do not fix the value and try again.
- The tool says it cannot reach the backend or that `BACKEND_URL` is not set: call `health` once,
  report its result or error as returned, and tell the user to start the backend (`python -m backend.app`).
  Report no lookup data.
- Never fill a gap from other tools or from what you know about the domain.
