"""Scoring tested directly (no web, no recordings): every band edge, each source's rules, errors and the empty case."""

from datetime import date

from backend.scoring import add_scores, average_of, score_crtsh, score_dns, score_rdap, score_source, verdict_for

TODAY = date(2026, 11, 9)


def days_ago(days):
    """A date text that many days before TODAY, in the same style the sources use."""
    return date.fromordinal(TODAY.toordinal() - days).isoformat() + "T00:00:00Z"


# ---- the verdict bands: test both sides of every edge ----

def test_band_edges():
    edges = {0: "likely_malware", 40: "likely_malware", 41: "undetermined", 60: "undetermined", 61: "likely_safe", 100: "likely_safe"}
    for average, expected in edges.items():
        assert verdict_for(average)[0] == expected, average


def test_verdict_labels():
    assert verdict_for(10)[1] == "Likely malware"
    assert verdict_for(50)[1] == "Undetermined"
    assert verdict_for(90)[1] == "Likely safe"


# ---- the average and its rounding ----

def test_average_skips_missing_scores_and_counts_the_rest():
    assert average_of([60, None, 90]) == (75, 2)
    assert average_of([10, 20, 30]) == (20, 3)


def test_average_rounds_half_up():
    assert average_of([40, 41]) == (41, 2)  # 40.5 -> 41
    assert average_of([40, 40, 41]) == (40, 3)  # 40.33 -> 40


def test_average_of_nothing():
    assert average_of([None, None, None]) == (None, 0)


# ---- each source's scoring ----

def test_dns_scores():
    assert score_dns({"A": [{"value": "1.2.3.4", "ttl": 1}], "AAAA": []})[0] == 60
    assert score_dns({"A": [], "AAAA": [{"value": "::1", "ttl": 1}]})[0] == 60
    assert score_dns({"A": [], "AAAA": []})[0] == 40


def test_rdap_scores_and_their_edges():
    cases = {0: 15, 29: 15, 30: 40, 364: 40, 365: 70, 1824: 70, 1825: 90, 10000: 90}
    for days, expected in cases.items():
        assert score_rdap({"registered": days_ago(days)}, TODAY)[0] == expected, days
    assert score_rdap({"registered": None}, TODAY)[0] == 50


def test_crtsh_scores_and_their_edges():
    cases = {0: 25, 29: 25, 30: 50, 364: 50, 365: 75, 4000: 75}
    for days, expected in cases.items():
        assert score_crtsh({"first_seen": days_ago(days)}, TODAY)[0] == expected, days


def test_a_crtsh_date_without_a_timezone_works():
    assert score_crtsh({"first_seen": "2020-01-01T00:00:00"}, TODAY)[0] == 75


def test_error_has_no_score_and_not_found_is_neutral():
    error = {"status": "error", "data": None, "error": {"code": "timeout", "message": "x"}}
    assert score_source("rdap", error, TODAY)[0] is None
    for key in ("dns", "rdap", "crtsh"):
        assert score_source(key, {"status": "not_found", "data": None}, TODAY)[0] == 50


# ---- the whole assessment ----

def sample_sources():
    return {
        "dns": {"status": "ok", "data": {"A": [{"value": "1.2.3.4", "ttl": 1}], "AAAA": []}},
        "rdap": {"status": "ok", "data": {"registered": days_ago(10)}},
        "crtsh": {"status": "ok", "data": {"first_seen": days_ago(2000)}},
    }


def test_assessment_with_three_scores():
    sources = sample_sources()
    assessment = add_scores(sources, TODAY)
    # (60 + 15 + 75) / 3 = 50
    assert assessment == {"score_min": 0, "score_max": 100, "average": 50, "sources_used": 3, "sources_total": 3,
                          "verdict": "undetermined", "verdict_label": "Undetermined"}
    assert sources["rdap"]["score"] == 15 and sources["rdap"]["score_reason"] != ""


def test_a_failed_source_is_left_out_and_counted():
    sources = sample_sources()
    sources["crtsh"] = {"status": "error", "data": None, "error": {"code": "upstream_error", "message": "x"}}
    assessment = add_scores(sources, TODAY)
    assert sources["crtsh"]["score"] is None
    assert assessment["average"] == 38 and assessment["sources_used"] == 2  # (60 + 15) / 2 = 37.5 -> 38
    assert assessment["verdict"] == "likely_malware"


def test_no_source_answered_gives_no_assessment():
    failed = {"status": "error", "data": None, "error": {"code": "timeout", "message": "x"}}
    sources = {"dns": dict(failed), "rdap": dict(failed), "crtsh": dict(failed)}
    assert add_scores(sources, TODAY) is None


def test_all_not_found_is_undetermined():
    sources = {k: {"status": "not_found", "data": None} for k in ("dns", "rdap", "crtsh")}
    assessment = add_scores(sources, TODAY)
    assert assessment["average"] == 50 and assessment["verdict"] == "undetermined"
