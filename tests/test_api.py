"""The whole backend, tested with RECORDED real answers (and a few clearly labelled SIMULATED failures)."""

import re

import requests
import responses

from conftest import load, replay, replay_all

HIT = "/api/v1/domain/example.com"
UNKNOWN = "/api/v1/domain/this-does-not-exist-zzqq1234.com"

# Patterns that match every address of one source, used to make a source fail on purpose.
ANY_DNS = re.compile(r"https://dns\.google/resolve.*")
ANY_RDAP = re.compile(r"https://rdap\.org/.*")
ANY_CRTSH = re.compile(r"https://crt\.sh/.*")


def statuses(body):
    """{"dns": "ok", "rdap": "ok", ...} from a backend answer."""
    result = {}
    for key, block in body["sources"].items():
        result[key] = block["status"]
    return result


# ---- a name that the sources know (recorded real answers) ----

def test_a_known_name_returns_all_three_sources(client, mock):
    replay_all(mock, "hit")
    response = client.get(HIT)
    body = response.get_json()
    assert response.status_code == 200
    assert body["ioc"] == {"type": "domain", "input": "example.com", "value": "example.com"}
    assert statuses(body) == {"dns": "ok", "rdap": "ok", "crtsh": "ok"}


def test_the_dns_data_matches_the_recording(client, mock):
    replay_all(mock, "hit")
    dns = client.get(HIT).get_json()["sources"]["dns"]["data"]

    # Find the recorded answer to the "A" question (type=1) and read the addresses out of it by hand.
    recorded_addresses = []
    for step in load("dns", "hit"):
        if step["url"].endswith("type=1"):
            import json
            for item in json.loads(step["body"])["Answer"]:
                recorded_addresses.append(item["data"])

    found_addresses = []
    for record in dns["A"]:
        found_addresses.append(record["value"])
    assert found_addresses == recorded_addresses
    assert len(found_addresses) > 0
    assert dns["resolver"] == "dns.google" and dns["rcode"] == "NOERROR"
    for record_type in ("A", "AAAA", "NS", "MX", "TXT"):
        assert record_type in dns


def test_rdap_follows_the_recorded_redirect(client, mock):
    replay_all(mock, "hit")
    rdap = client.get(HIT).get_json()["sources"]["rdap"]["data"]
    assert "Internet Assigned Numbers Authority" in rdap["registrar"]
    assert rdap["registered"] == "1995-08-14T04:00:00Z"
    assert rdap["registry_url"].startswith("https://rdap.verisign.com/com/v1/domain/example.com")


def test_the_crtsh_summary(client, mock):
    replay_all(mock, "hit")
    crtsh = client.get(HIT).get_json()["sources"]["crtsh"]["data"]
    assert crtsh["certificate_count"] > 0
    assert crtsh["first_seen"] <= crtsh["last_seen"]
    assert len(crtsh["names"]) <= 50 and len(crtsh["issuers"]) <= 10


# ---- scores and verdict through the API ----

def test_every_source_has_a_score_and_the_answer_has_an_assessment(client, mock):
    replay_all(mock, "hit")
    body = client.get(HIT).get_json()
    for block in body["sources"].values():
        assert 0 <= block["score"] <= 100 and block["score_reason"] != ""
    assessment = body["assessment"]
    assert assessment["sources_used"] == 3 and assessment["sources_total"] == 3
    assert assessment["score_min"] == 0 and assessment["score_max"] == 100
    assert assessment["average"] == 25 and assessment["verdict"] == "definitely_safe"  # example.com: resolves, registered 1995, old certificates
    assert assessment["verdict_note"] is None


def test_unknown_name_is_undetermined(client, mock):
    replay_all(mock, "unknown")
    assessment = client.get(UNKNOWN).get_json()["assessment"]
    assert assessment["average"] == 55 and assessment["verdict"] == "undetermined"  # (55 + 50 + 60) / 3


def test_a_failing_source_has_a_null_score_and_is_not_averaged(client, mock):
    replay(mock, "dns", "hit")
    replay(mock, "rdap", "hit")
    replay(mock, "crtsh", "error_502")
    body = client.get(HIT).get_json()
    assert body["sources"]["crtsh"]["score"] is None
    assert body["assessment"]["sources_used"] == 2 and body["assessment"]["sources_total"] == 3
    # (40 + 10) / 2 = 25 would be "definitely safe", but with only 2 of 3 sources it is lowered to "likely safe"
    assert body["assessment"]["verdict"] == "likely_safe" and "2 of 3" in body["assessment"]["verdict_note"]


def test_all_failed_answer_says_not_graded_in_its_assessment(client, mock):
    mock.add(responses.GET, ANY_DNS, status=502, body="x")
    mock.add(responses.GET, ANY_RDAP, status=502, body="x")
    mock.add(responses.GET, ANY_CRTSH, status=502, body="x")
    assessment = client.get(HIT).get_json()["assessment"]
    assert assessment["verdict"] == "not_graded" and assessment["average"] is None


# ---- a valid name always gets a 200: one answering source is enough, and none gives a 'not graded' assessment (no 5xx) ----

def test_one_failure_is_still_graded(client, mock):
    replay(mock, "dns", "hit")
    replay(mock, "rdap", "hit")
    replay(mock, "crtsh", "error_502")
    response = client.get(HIT)
    assert response.status_code == 200
    assert response.get_json()["assessment"]["sources_used"] == 2


def test_two_failures_are_still_graded_from_the_one_answer(client, mock):
    replay(mock, "dns", "hit")
    replay(mock, "crtsh", "error_502")
    mock.add(responses.GET, ANY_RDAP, status=503, body="unavailable")
    response = client.get(HIT)
    body = response.get_json()
    assert response.status_code == 200
    assert statuses(body) == {"dns": "ok", "rdap": "error", "crtsh": "error"}
    assert body["assessment"]["sources_used"] == 1 and body["assessment"]["sources_total"] == 3
    assert body["sources"]["dns"]["score"] is not None and body["sources"]["rdap"]["score"] is None


def test_one_answer_never_gives_a_definitely_verdict_and_the_note_says_why(client, mock):
    mock.add(responses.GET, ANY_DNS, status=503, body="x")
    replay(mock, "rdap", "hit")  # RDAP alone scores 10, which on its own would be "definitely safe"
    mock.add(responses.GET, ANY_CRTSH, status=503, body="x")
    assessment = client.get(HIT).get_json()["assessment"]
    assert assessment["sources_used"] == 1
    assert assessment["verdict"] == "likely_safe" and "only 1 of 3" in assessment["verdict_note"]


def test_one_not_found_answer_is_enough_and_is_graded(client, mock):
    mock.add(responses.GET, ANY_DNS, status=502, body="x")
    mock.add(responses.GET, ANY_RDAP, status=502, body="x")
    replay(mock, "crtsh", "unknown")  # the only answer, and it is "not found" (an answer, with a score)
    response = client.get(UNKNOWN)
    body = response.get_json()
    assert response.status_code == 200
    assert body["sources"]["crtsh"]["status"] == "not_found"
    assert body["assessment"]["sources_used"] == 1


def test_three_failures_still_give_a_200_and_say_not_graded(client, mock):
    mock.add(responses.GET, ANY_DNS, status=502, body="x")
    mock.add(responses.GET, ANY_RDAP, status=502, body="x")
    mock.add(responses.GET, ANY_CRTSH, status=502, body="x")
    response = client.get(HIT)
    body = response.get_json()
    assert response.status_code == 200
    assert body["ioc"]["value"] == "example.com"
    assert statuses(body) == {"dns": "error", "rdap": "error", "crtsh": "error"}
    assert all(block["score"] is None for block in body["sources"].values())
    assessment = body["assessment"]
    assert assessment["verdict"] == "not_graded" and assessment["verdict_label"] == "Not graded"
    assert assessment["average"] is None and assessment["sources_used"] == 0 and assessment["sources_total"] == 3
    assert "no source answered" in assessment["verdict_note"]


def test_three_timeouts_also_give_a_200_and_keep_the_timeout_errors(client, mock):
    for pattern in (ANY_DNS, ANY_RDAP, ANY_CRTSH):
        mock.add(responses.GET, pattern, body=requests.exceptions.ReadTimeout("simulated"))
    response = client.get(HIT)
    body = response.get_json()
    assert response.status_code == 200
    assert all(block["error"]["code"] == "timeout" for block in body["sources"].values())
    assert body["assessment"]["verdict"] == "not_graded"


def test_two_not_found_answers_and_one_failure_are_graded(client, mock):
    replay(mock, "dns", "unknown")  # not_found is an answer
    replay(mock, "rdap", "unknown")  # not_found is an answer
    mock.add(responses.GET, ANY_CRTSH, status=502, body="x")  # the one failure
    response = client.get(UNKNOWN)
    body = response.get_json()
    assert response.status_code == 200
    assert statuses(body) == {"dns": "not_found", "rdap": "not_found", "crtsh": "error"}
    assert body["assessment"]["sources_used"] == 2 and body["assessment"]["average"] == 53  # (55 + 50) / 2 = 52.5


# ---- a name that no source knows ----

def test_an_unknown_name_is_not_found_everywhere_but_still_200(client, mock):
    replay_all(mock, "unknown")
    response = client.get(UNKNOWN)
    body = response.get_json()
    assert response.status_code == 200
    assert statuses(body) == {"dns": "not_found", "rdap": "not_found", "crtsh": "not_found"}
    for block in body["sources"].values():
        assert block["data"] is None
        assert "error" not in block


# ---- one source fails: the others still return ----

def test_a_recorded_real_crtsh_502_shows_an_error_and_keeps_the_other_sources(client, mock):
    replay(mock, "dns", "hit")
    replay(mock, "rdap", "hit")
    replay(mock, "crtsh", "error_502")  # a REAL crt.sh 502, recorded earlier
    response = client.get(HIT)
    body = response.get_json()
    assert response.status_code == 200
    assert statuses(body) == {"dns": "ok", "rdap": "ok", "crtsh": "error"}
    assert body["sources"]["crtsh"]["data"] is None
    assert body["sources"]["crtsh"]["error"] == {"code": "upstream_error", "message": "crt.sh returned HTTP 502"}
    assert len(body["sources"]["dns"]["data"]["A"]) > 0


# ---- crt.sh is asked one more time after an HTTP 5xx, but not after a timeout ----

def crtsh_calls(mock):
    """How many requests went to crt.sh."""
    return len([call for call in mock.calls if call.request.url.startswith("https://crt.sh/")])


def test_crtsh_502_then_a_good_answer_is_ok(client, mock):
    replay(mock, "dns", "hit")
    replay(mock, "rdap", "hit")
    mock.add(responses.GET, ANY_CRTSH, status=502, body="bad gateway")  # first try fails
    replay(mock, "crtsh", "hit")  # second try works (recorded real answer)
    body = client.get(HIT).get_json()
    assert body["sources"]["crtsh"]["status"] == "ok"
    assert crtsh_calls(mock) == 2
    assert body["assessment"]["sources_used"] == 3


def test_crtsh_two_502s_is_an_error_after_exactly_two_requests(client, mock):
    replay(mock, "dns", "hit")
    replay(mock, "rdap", "hit")
    mock.add(responses.GET, ANY_CRTSH, status=502, body="bad gateway")
    mock.add(responses.GET, ANY_CRTSH, status=503, body="unavailable")
    crtsh = client.get(HIT).get_json()["sources"]["crtsh"]
    assert crtsh["status"] == "error" and crtsh["error"]["message"] == "crt.sh returned HTTP 503"
    assert crtsh_calls(mock) == 2


def test_crtsh_timeout_is_not_retried(client, mock):
    replay(mock, "dns", "hit")
    replay(mock, "rdap", "hit")
    mock.add(responses.GET, ANY_CRTSH, body=requests.exceptions.ReadTimeout("simulated"))
    assert client.get(HIT).get_json()["sources"]["crtsh"]["error"]["code"] == "timeout"
    assert crtsh_calls(mock) == 1


def test_crtsh_404_is_not_retried(client, mock):
    replay(mock, "dns", "hit")
    replay(mock, "rdap", "hit")
    mock.add(responses.GET, ANY_CRTSH, status=404, body="not here")
    assert client.get(HIT).get_json()["sources"]["crtsh"]["error"]["message"] == "crt.sh returned HTTP 404"
    assert crtsh_calls(mock) == 1


# ---- SIMULATED failures: built by hand, because a real service cannot be asked to fail on command ----

def test_simulated_timeout_is_reported_as_timeout(client, mock):
    replay(mock, "dns", "hit")
    replay(mock, "crtsh", "hit")
    mock.add(responses.GET, ANY_RDAP, body=requests.exceptions.ReadTimeout("simulated"))
    body = client.get(HIT).get_json()
    assert body["sources"]["rdap"]["status"] == "error"
    assert body["sources"]["rdap"]["error"]["code"] == "timeout"
    assert body["sources"]["dns"]["status"] == "ok" and body["sources"]["crtsh"]["status"] == "ok"


def test_simulated_unreadable_answer_is_invalid_response(client, mock):
    replay(mock, "dns", "hit")
    replay(mock, "rdap", "hit")
    mock.add(responses.GET, ANY_CRTSH, status=200, body="<html>this is not JSON</html>")
    crtsh = client.get(HIT).get_json()["sources"]["crtsh"]
    assert crtsh["status"] == "error" and crtsh["error"]["code"] == "invalid_response"


def test_simulated_all_sources_failing_is_a_200_that_is_not_graded(client, mock):
    mock.add(responses.GET, ANY_DNS, status=502, body="bad gateway")
    mock.add(responses.GET, ANY_RDAP, status=502, body="bad gateway")
    mock.add(responses.GET, ANY_CRTSH, status=502, body="bad gateway")
    response = client.get(HIT)
    body = response.get_json()
    assert response.status_code == 200
    assert statuses(body) == {"dns": "error", "rdap": "error", "crtsh": "error"}
    assert body["assessment"]["verdict"] == "not_graded"


# ---- bad input and unknown addresses ----

def test_an_invalid_name_is_400_and_no_outside_service_is_contacted(client, mock):
    response = client.get("/api/v1/domain/10.0.0.1")
    assert response.status_code == 400
    assert response.get_json() == {
        "error": "not a valid DNS name: 10.0.0.1 (IP addresses are not accepted)",
        "input": "10.0.0.1",
    }
    assert len(mock.calls) == 0


def test_health_and_unknown_address(client):
    assert client.get("/api/v1/health").get_json() == {"status": "ok"}
    missing = client.get("/nope")
    assert missing.status_code == 404
    assert missing.get_json() == {"error": "not found"}
