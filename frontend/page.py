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
WAIT_SECONDS = 100  # how long to wait for the backend (it asks several slow services)

TITLES = {"dns": "DNS (Google Public DNS)"}
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


def show_source(key, block):
    """Show one source's result: its data, or 'not found', or its error."""
    st.subheader(TITLES.get(key, key))
    if block["status"] == "ok":
        st.success("OK: the source answered with data.")
        show_dns_data(block["data"])
    elif block["status"] == "not_found":
        st.info("Not found: the source answered that it knows nothing about this name.")
    else:
        code = block["error"]["code"]
        message = block["error"]["message"]
        st.error(f"Error ({code}): {message}. This does NOT mean there is no data; the check could not be completed.")


st.title("IOC Enrichment Portal: DNS names")
st.write("Enter a domain name to see what public sources say about it. They report facts; none of them gives a verdict.")
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
    with st.spinner("Asking the backend... (this can take a while)"):
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
        for key, block in body["sources"].items():
            show_source(key, block)
        with st.expander("Raw JSON from the backend"):
            st.json(body)
