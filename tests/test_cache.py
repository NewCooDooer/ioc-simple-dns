"""Tests for the cache. Like all tests here they run offline: the fake web replays recordings, and sockets are blocked.

Time is faked too: the `clock` fixture lets a test "move time" forward without waiting.
"""

from urllib.parse import quote, urlparse

import pytest
import requests
import responses

from backend import cache
from tests.conftest import load, replay

GOOGLE_HEADER = "private, max-age=300"  # what Google really sent for example.com (checked 2026-11-06)
UNKNOWN_NAME = "this-does-not-exist-zzqq1234.com"
RDAP_HOSTS = ("rdap.org", "rdap.verisign.com")  # rdap.org redirects to the registry, so RDAP uses two hosts


@pytest.fixture
def clock(monkeypatch):
    """A fake clock. Start at 1000 seconds; a test moves time with  clock[0] += 301."""
    now = [1000.0]
    monkeypatch.setattr(cache, "clock", lambda: now[0])
    return now


def replay_dns(mock, case, header=GOOGLE_HEADER):
    """Like conftest.replay, but the fake Google DNS also sends a Cache-Control header (the recordings keep no headers)."""
    for step in load("dns", case):
        headers = {} if header is None else {"Cache-Control": header}
        mock.add(responses.GET, step["url"], status=step["status"], body=step.get("body", ""), headers=headers)


def replay_everything(mock, case="hit", crtsh_case=None, dns_header=GOOGLE_HEADER):
    replay_dns(mock, case, dns_header)
    replay(mock, "rdap", case)
    replay(mock, "crtsh", crtsh_case or case)


def look_up(client, typed):
    return client.get("/api/v1/domain/" + quote(typed))


def requests_sent(mock, source):
    """How many outbound requests (including redirect hops) went to one source."""
    hosts = {"dns": ("dns.google",), "rdap": RDAP_HOSTS, "crtsh": ("crt.sh",)}[source]
    return sum(1 for call in mock.calls if urlparse(call.request.url).hostname in hosts)


def cache_age(response, source):
    """The age the backend reported for one source in its X-Cache-Age-<source> header, or None if there is no such header."""
    value = response.headers.get(f"X-Cache-Age-{source}")
    return int(value) if value is not None else None


# ---- a miss, then a hit ----

def test_first_lookup_is_a_miss_and_second_is_a_hit(client, mock, clock):
    replay_everything(mock)

    first = look_up(client, "example.com")
    sent_after_first = len(mock.calls)
    assert sent_after_first == 8  # 5 DNS + 2 RDAP (redirect) + 1 crt.sh
    for source in ("dns", "rdap", "crtsh"):
        assert cache_age(first, source) is None  # fresh: no header

    clock[0] += 42
    second = look_up(client, "example.com")
    assert len(mock.calls) == sent_after_first  # nothing was sent: the cache answered
    for source in ("dns", "rdap", "crtsh"):
        assert cache_age(second, source) == 42
    assert second.get_json() == first.get_json()  # the body is exactly the same: the cache adds nothing to it


def test_the_body_never_carries_cache_fields(client, mock, clock):
    replay_everything(mock)
    look_up(client, "example.com")
    clock[0] += 42
    for response in (look_up(client, "example.com"), look_up(client, "example.com")):  # a hit, twice
        for block in response.get_json()["sources"].values():
            assert "cached" not in block and "age_seconds" not in block


@pytest.mark.parametrize("typed", ["EXAMPLE.COM", " example.com ", "example.com.", "Example.Com."])
def test_different_spellings_share_one_entry(client, mock, clock, typed):
    replay_everything(mock)
    look_up(client, "example.com")
    sent = len(mock.calls)

    response = look_up(client, typed)
    assert len(mock.calls) == sent
    assert all(cache_age(response, source) is not None for source in ("dns", "rdap", "crtsh"))


def test_different_names_and_sources_never_share_an_entry():
    result = {"status": "ok", "data": {"x": 1}}
    cache.store("rdap", "example.com", result, 60)
    assert cache.lookup("rdap", "example.com") == (result, 0)  # the stored result, and its age
    assert cache.lookup("rdap", "example.org") is None  # another name
    assert cache.lookup("crtsh", "example.com") is None  # another source


# ---- expiry ----

def test_dns_is_kept_for_the_time_in_googles_cache_control_header(client, mock, clock):
    replay_everything(mock)
    look_up(client, "example.com")
    assert requests_sent(mock, "dns") == 5

    clock[0] += 299
    look_up(client, "example.com")
    assert requests_sent(mock, "dns") == 5  # 299 s < max-age 300: still cached

    clock[0] += 2  # now 301 s after the first lookup
    response = look_up(client, "example.com")
    assert requests_sent(mock, "dns") == 10  # expired: asked Google again
    assert cache_age(response, "dns") is None
    assert cache_age(response, "rdap") is not None  # RDAP is kept for an hour, so it was not asked again
    assert requests_sent(mock, "rdap") == 2


def test_rdap_and_crtsh_entries_expire_after_their_own_times(client, mock, clock):
    replay_everything(mock)
    look_up(client, "example.com")

    clock[0] += cache.RDAP_OK_SECONDS - 1
    look_up(client, "example.com")
    assert requests_sent(mock, "rdap") == 2  # just under an hour: still cached

    clock[0] += 2
    look_up(client, "example.com")
    assert requests_sent(mock, "rdap") == 4  # expired: asked again (2 requests: redirect + registry)
    assert requests_sent(mock, "crtsh") == 1  # crt.sh is kept for 6 hours

    clock[0] += cache.CRTSH_OK_SECONDS
    look_up(client, "example.com")
    assert requests_sent(mock, "crtsh") == 2


def test_not_found_is_cached_but_for_less_time(client, mock, clock):
    replay_everything(mock, case="unknown")
    first = look_up(client, UNKNOWN_NAME).get_json()
    assert all(block["status"] == "not_found" for block in first["sources"].values())
    assert requests_sent(mock, "rdap") == 2 and requests_sent(mock, "crtsh") == 1

    clock[0] += cache.RDAP_NOT_FOUND_SECONDS - 1
    look_up(client, UNKNOWN_NAME)
    assert requests_sent(mock, "rdap") == 2  # "not found" was kept

    clock[0] += 2
    look_up(client, UNKNOWN_NAME)
    assert requests_sent(mock, "rdap") == 4  # but only for 5 minutes
    assert requests_sent(mock, "crtsh") == 1  # crt.sh keeps "not found" for 10 minutes

    clock[0] += cache.CRTSH_NOT_FOUND_SECONDS
    look_up(client, UNKNOWN_NAME)
    assert requests_sent(mock, "crtsh") == 2


def test_dns_without_a_cache_control_header_is_not_kept(client, mock, clock):
    replay_everything(mock, dns_header=None)
    look_up(client, "example.com")
    look_up(client, "example.com")
    assert requests_sent(mock, "dns") == 10  # asked twice: with no header there is no permission to keep it
    assert requests_sent(mock, "rdap") == 2  # the other sources were still cached


# ---- errors are never cached ----

def test_a_crtsh_502_is_not_cached(client, mock, clock):
    replay_everything(mock, crtsh_case="error_502")
    first = look_up(client, "example.com").get_json()
    assert first["sources"]["crtsh"]["status"] == "error"

    second = look_up(client, "example.com")
    # Each lookup asks crt.sh twice (one retry after an HTTP 5xx), so 2 lookups = 4 requests. The error was not remembered:
    # the second lookup asked crt.sh again instead of using a stored copy.
    assert requests_sent(mock, "crtsh") == 4
    assert cache_age(second, "crtsh") is None
    assert requests_sent(mock, "rdap") == 2  # the good answers from the other sources were cached
    assert cache_age(second, "rdap") is not None


@pytest.mark.parametrize("how_it_fails", ["429", "500", "timeout"])
def test_rdap_failures_are_not_cached(client, mock, clock, how_it_fails):
    replay_dns(mock, "hit")
    replay(mock, "crtsh", "hit")
    if how_it_fails == "timeout":
        mock.add(responses.GET, "https://rdap.org/domain/example.com", body=requests.exceptions.ReadTimeout())  # simulated
    else:
        mock.add(responses.GET, "https://rdap.org/domain/example.com", status=int(how_it_fails))

    first = look_up(client, "example.com").get_json()
    assert first["sources"]["rdap"]["status"] == "error"
    look_up(client, "example.com")
    assert requests_sent(mock, "rdap") == 2  # asked again, one request each time (no redirect happened)


def test_the_cache_refuses_errors_and_zero_lifetimes():
    cache.store("rdap", "a.com", {"status": "error", "data": None, "error": {"code": "timeout", "message": "x"}}, 60)
    cache.store("rdap", "b.com", {"status": "ok", "data": {}}, 0)
    assert cache.lookup("rdap", "a.com") is None
    assert cache.lookup("rdap", "b.com") is None


def test_invalid_input_never_reaches_the_cache_or_a_source(client, mock):
    assert look_up(client, "10.0.0.1").status_code == 400
    assert len(mock.calls) == 0
