# IOC Enrichment Portal (DNS names), the simple version

**Status: Milestone 0 (design).** The plan is in [`design.md`](design.md); the code arrives in the next milestones. This is a work in progress. This is a deliberately small version of the IOC Enrichment Portal, built step by step so that every line can be explained.
It follows the same assignment specifications as the full version, with the simplest possible code: plain functions, no async, no extras.

- A Flask **backend** that looks a DNS name up in three real, keyless sources (Google DNS over HTTPS, RDAP, crt.sh) and returns one JSON answer
- A Streamlit **frontend** that only talks to the backend
- Tests that replay recorded real responses and need no network

The full, finished version (with a themed interface and concurrent lookups) is here:
https://github.com/NewCooDooer/ioc-enrichment-portal-dns

This page will be filled in (install, run, API contract, tests) as the project is built, one pull request per milestone.
