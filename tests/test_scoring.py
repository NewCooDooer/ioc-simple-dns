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
                          "verdict": "undetermined", "verdict_label": "Undetermined", "verdict_note": None}
    assert sources["rdap"]["score"] == 15 and sources["rdap"]["score_reason"] != ""


def test_a_failed_source_is_left_out_and_counted():
    sources = sample_sources()
    sources["crtsh"] = {"status": "error", "data": None, "error": {"code": "upstream_error", "message": "x"}}
    assessment = add_scores(sources, TODAY)
    assert sources["crtsh"]["score"] is None
    assert assessment["average"] == 38 and assessment["sources_used"] == 2  # (60 + 15) / 2 = 37.5 -> 38
    # 38 would be "likely malware", but only 2 of 3 sources scored, so the verdict is capped (the papervinegames case)
    assert assessment["verdict"] == "undetermined"
    assert "2 of 3" in assessment["verdict_note"]


def test_no_source_answered_gives_no_assessment():
    failed = {"status": "error", "data": None, "error": {"code": "timeout", "message": "x"}}
    sources = {"dns": dict(failed), "rdap": dict(failed), "crtsh": dict(failed)}
    assert add_scores(sources, TODAY) is None


def test_all_not_found_is_undetermined():
    sources = {k: {"status": "not_found", "data": None} for k in ("dns", "rdap", "crtsh")}
    assessment = add_scores(sources, TODAY)
    assert assessment["average"] == 50 and assessment["verdict"] == "undetermined"


# ---- a firm verdict needs all three sources: both ends of the bands with 3, 2 and 1 sources used ----

ERROR = {"status": "error", "data": None, "error": {"code": "upstream_error", "message": "x"}}


def test_verdict_by_number_of_sources_used():
    # DNS 40 / 60 and RDAP 15 / 90 are produced by real rules; build low and high sets from them.
    low_dns = {"status": "ok", "data": {"A": [], "AAAA": []}}  # 40
    high_rdap = {"status": "ok", "data": {"registered": days_ago(4000)}}  # 90
    low_rdap = {"status": "ok", "data": {"registered": days_ago(1)}}  # 15
    high_crtsh = {"status": "ok", "data": {"first_seen": days_ago(4000)}}  # 75
    low_crtsh = {"status": "ok", "data": {"first_seen": days_ago(1)}}  # 25

    # all three: low end is likely malware (40, 15, 25 -> 27), high end is likely safe (60, 90, 75 -> 75)
    low = add_scores({"dns": dict(low_dns), "rdap": dict(low_rdap), "crtsh": dict(low_crtsh)}, TODAY)
    assert low["verdict"] == "likely_malware" and low["verdict_note"] is None
    high_dns = {"status": "ok", "data": {"A": [{"value": "1.2.3.4", "ttl": 1}], "AAAA": []}}
    high = add_scores({"dns": dict(high_dns), "rdap": dict(high_rdap), "crtsh": dict(high_crtsh)}, TODAY)
    assert high["verdict"] == "likely_safe" and high["verdict_note"] is None

    # two used: the same low and high averages are capped
    low2 = add_scores({"dns": dict(low_dns), "rdap": dict(low_rdap), "crtsh": dict(ERROR)}, TODAY)
    assert low2["average"] == 28 and low2["sources_used"] == 2 and low2["verdict"] == "undetermined"
    high2 = add_scores({"dns": dict(high_dns), "rdap": dict(high_rdap), "crtsh": dict(ERROR)}, TODAY)
    assert high2["average"] == 75 and high2["sources_used"] == 2 and high2["verdict"] == "undetermined"
    assert high2["verdict_note"] is not None

    # one used: capped as well, at both ends
    low1 = add_scores({"dns": dict(ERROR), "rdap": dict(low_rdap), "crtsh": dict(ERROR)}, TODAY)
    assert low1["average"] == 15 and low1["sources_used"] == 1 and low1["verdict"] == "undetermined"
    high1 = add_scores({"dns": dict(ERROR), "rdap": dict(high_rdap), "crtsh": dict(ERROR)}, TODAY)
    assert high1["average"] == 90 and high1["sources_used"] == 1 and high1["verdict"] == "undetermined"


def test_the_papervinegames_case_scores_60_and_15_with_crtsh_in_error():
    sources = {
        "dns": {"status": "ok", "data": {"A": [{"value": "1.2.3.4", "ttl": 1}], "AAAA": []}},  # 60
        "rdap": {"status": "ok", "data": {"registered": days_ago(5)}},  # 15
        "crtsh": dict(ERROR),
    }
    assessment = add_scores(sources, TODAY)
    assert assessment["average"] == 38 and assessment["verdict"] == "undetermined"


def test_scoring_does_not_change_the_original_blocks():
    """Cached results are shared between requests, so scoring must work on copies and leave the originals alone."""
    originals = sample_sources()
    given = {key: block for key, block in originals.items()}
    add_scores(given, TODAY)
    for block in originals.values():
        assert "score" not in block and "score_reason" not in block
