"""Shared test helpers. They replay RECORDED real answers, so no test ever makes a real network call."""

import json
from pathlib import Path

import pytest
import responses

from backend import cache
from backend.app import app

FIXTURES = Path(__file__).parent / "fixtures"


def load(source, case):
    """Read one recording (a list of steps: address, status number, body) from tests/fixtures/."""
    return json.loads((FIXTURES / source / f"{case}.json").read_text())["steps"]


def replay(mock, source, case):
    """Tell the fake web to answer each recorded request with the answer that was recorded for it."""
    for step in load(source, case):
        headers = {}
        if "location" in step:
            headers["Location"] = step["location"]  # a recorded redirect: the fake web will redirect too
        mock.add(responses.GET, step["url"], status=step["status"], body=step.get("body", ""), headers=headers)


def replay_all(mock, case, crtsh_case=None):
    """Replay the recordings of all three sources (optionally using a different recording for crt.sh)."""
    replay(mock, "dns", case)
    replay(mock, "rdap", case)
    replay(mock, "crtsh", crtsh_case or case)


@pytest.fixture(autouse=True)
def empty_cache():
    """Start every test with an empty cache, so one test's answers can never leak into the next. (autouse = no test has to ask for it.)"""
    cache.clear_cache()


@pytest.fixture
def mock():
    """A fake web. While it is active, requests never reach the real internet."""
    with responses.RequestsMock(assert_all_requests_are_fired=False) as fake_web:
        yield fake_web


@pytest.fixture
def client():
    """A test copy of the backend that we can send requests to without starting a server."""
    return app.test_client()
