"""The web page. It gets ALL its data from the backend and never calls a source itself.

Start it with:  streamlit run frontend/page.py --server.port 8510
Streamlit runs this whole file again, from top to bottom, every time the page loads or someone clicks.
"""

import os
from urllib.parse import quote

import requests
import streamlit as st

# Where the backend lives. Read from the environment, or use the default.
BACKEND_URL = os.environ.get("BACKEND_URL", "http://127.0.0.1:8010")
WAIT_SECONDS = 100  # how long to wait for the backend (it asks three slow services one after another)

TITLES = {"dns": "DNS (Google Public DNS)", "rdap": "Registration (RDAP)", "crtsh": "Certificates (crt.sh)"}
RECORD_TYPES = ["A", "AAAA", "NS", "MX", "TXT"]


def show_dns_data(data):
    """Show each kind of DNS record as a small table."""
    for record_type in RECORD_TYPES:
        records = data[record_type]
        st.write(f"**{record_type}**")
        if records:
            st.table(records)  # a list of {"value": ..., "ttl": ...} becomes a table
        else:
            st.write("no records")


def show_rdap_data(data):
    """Show the registration facts as a small two-column table."""
    st.table(
        {
            "Registrar": data["registrar"] or "not stated",
            "Registered": data["registered"] or "not stated",
            "Expires": data["expires"] or "not stated",
            "Last changed": data["last_changed"] or "not stated",
            "Status flags": ", ".join(data["statuses"]) or "none",
            "Name servers": ", ".join(data["nameservers"]) or "none",
        }
    )
    st.write(f"Registry record: {data['registry_url']}")


def show_crtsh_data(data):
    """Show the certificate summary."""
    st.write(f"**{data['certificate_count']}** certificates, first seen **{data['first_seen']}**, most recent **{data['last_seen']}**")
    st.write("**Issuers**")
    for issuer in data["issuers"]:
        st.text(issuer)
    st.write(f"**Names on the certificates** ({len(data['names'])} shown)")
    for name in data["names"]:
        st.text(name)
    if data["names_truncated"]:
        st.write("The list is cut short: more names exist.")


def show_assessment(body):
    """Show the three scores, the average and the verdict, with the caveat that it is only a rough guess."""
    assessment = body["assessment"]
    st.markdown("### Verdict")
    st.write(f"**{assessment['verdict_label']}**: average score {assessment['average']} "
             f"(0 = definitely safe, 100 = definitely malware), from {assessment['sources_used']} of {assessment['sources_total']} sources.")
    if assessment["verdict_note"] is not None:
        st.warning(assessment["verdict_note"].capitalize() + ".")
    rows = {}
    for key, block in body["sources"].items():
        score = block["score"]
        rows[TITLES.get(key, key)] = {"Score": "no score" if score is None else score, "Why": block["score_reason"]}
    st.table(rows)
    st.caption("This verdict is built from public registration facts (name age, DNS, certificates). It is a risk indicator, not a malware test: it cannot see blocklists or past incidents. Check the facts below before acting on it.")


def describe_age(seconds):
    """Turn a number of seconds into a short phrase such as '42 s', '7 min' or '2 h'."""
    if seconds < 60:
        return f"{seconds} s"
    if seconds < 3600:
        return f"{seconds // 60} min"
    return f"{seconds // 3600} h"


def cache_age(response, key):
    """Seconds since this source's result was fetched, read from the backend's X-Cache-Age-<source> header.
    None if the header is missing, which means the result was just fetched."""
    value = response.headers.get(f"X-Cache-Age-{key}")
    return int(value) if value is not None else None


def show_source(key, block, age=None):
    """Show one source's result: its data, or 'not found', or its error. `age` is set only for a cached result."""
    st.subheader(TITLES.get(key, key))
    # A cached result can be out of date, so the analyst must be able to see that it is not fresh.
    if age is not None:
        st.caption(f"Cached result, fetched {describe_age(age)} ago. It may have changed since.")
    if block["status"] == "ok":
        st.success("OK: the source answered with data.")
        if key == "dns":
            show_dns_data(block["data"])
        elif key == "rdap":
            show_rdap_data(block["data"])
        elif key == "crtsh":
            show_crtsh_data(block["data"])
    elif block["status"] == "not_found":
        st.info("Not found: the source answered that it knows nothing about this name.")
        if key == "rdap":
            st.caption("For RDAP this also happens for subdomains (it only covers registered domains) and for top-level domains it does not cover, such as .de or .io.")
    else:
        code = block["error"]["code"]
        message = block["error"]["message"]
        st.error(f"Error ({code}): {message}. This does NOT mean there is no data; the check could not be completed.")


st.title("IOC Enrichment Portal: DNS names")
st.write("Enter a domain name to see what public sources say about it. They report facts; the page turns them into a rough score and verdict.")
st.warning("Do not enter internal or private names: lookups go to outside services.")

# A form lets the user press Enter as well as click the button.
with st.form("lookup"):
    name = st.text_input("DNS name", placeholder="example.com")
    submitted = st.form_submit_button("Look up")

if submitted:
    if name.strip() == "":
        st.warning("Please type a domain name.")
        st.stop()

    # Ask the backend. quote() makes the name safe to put inside a web address.
    url = f"{BACKEND_URL}/api/v1/domain/{quote(name.strip(), safe='')}"
    with st.spinner("Asking the backend... crt.sh is slow and can take up to a minute."):
        try:
            response = requests.get(url, timeout=WAIT_SECONDS)
        except requests.RequestException:
            st.error("Could not reach the backend. Is it running? Start it with: python -m backend.app")
            st.stop()

    body = response.json()
    if response.status_code == 400:
        st.warning(f"Invalid input: {body['error']}")
    elif response.status_code == 502:
        st.error("Every source failed, so there is nothing to show.")
        for key, block in body["sources"].items():
            show_source(key, block)
    elif response.status_code != 200:
        st.error(f"Unexpected answer from the backend: {body.get('error', response.status_code)}")
    else:
        st.markdown(f"### Results for `{body['ioc']['value']}`")
        show_assessment(body)
        for key, block in body["sources"].items():
            show_source(key, block, cache_age(response, key))
        with st.expander("Raw JSON from the backend"):
            st.json(body)
