"""Scoring tested directly (no web, no recordings): every band edge, every signal, errors and the empty case."""

from datetime import date

from backend.scoring import add_scores, average_of, verdict_for
from backend.signals import finish, name_shape_points, odd_address, score_crtsh, score_dns, score_rdap

TODAY = date(2026, 11, 9)
NAME = "example.com"
ERROR = {"status": "error", "data": None, "error": {"code": "upstream_error", "message": "x"}}


def days_ago(days):
    """A date text that many days before TODAY, in the same style the sources use."""
    return date.fromordinal(TODAY.toordinal() - days).isoformat() + "T00:00:00Z"


def dns_data(*addresses, ttl=300):
    """DNS data with these A addresses (none = the name exists but has no address)."""
    return {"A": [{"value": address, "ttl": ttl} for address in addresses], "AAAA": []}


def rdap_data(days, statuses=()):
    return {"registered": None if days is None else days_ago(days), "statuses": list(statuses)}


# ---- the verdict bands: test both sides of every edge ----

def test_band_edges():
    edges = {0: "definitely_safe", 30: "definitely_safe", 31: "likely_safe", 45: "likely_safe", 46: "undetermined",
             55: "undetermined", 56: "likely_malware", 70: "likely_malware", 71: "definitely_malware", 100: "definitely_malware"}
    for average, expected in edges.items():
        assert verdict_for(average)[0] == expected, average


def test_verdict_labels():
    labels = {10: "Definitely safe", 40: "Likely safe", 50: "Undetermined", 60: "Likely malware", 90: "Definitely malware"}
    for average, expected in labels.items():
        assert verdict_for(average)[1] == expected


# ---- the average and its rounding ----

def test_average_skips_missing_scores_and_counts_the_rest():
    assert average_of([60, None, 90]) == (75, 2)
    assert average_of([10, 20, 30]) == (20, 3)


def test_average_rounds_half_up():
    assert average_of([40, 41]) == (41, 2)  # 40.5 -> 41
    assert average_of([40, 40, 41]) == (40, 3)  # 40.33 -> 40


def test_average_of_nothing():
    assert average_of([None, None, None]) == (None, 0)


# ---- finish: starting point, points, clamping, reasons ----

def test_finish_starts_at_50_adds_points_and_lists_reasons():
    assert finish([(-10, "a"), (35, "b")]) == (75, "a (-10); b (+35)")
    assert finish([]) == (50, "no signal fired")


def test_finish_keeps_the_score_between_0_and_100():
    assert finish([(-40, "a"), (-40, "b")])[0] == 0
    assert finish([(40, "a"), (40, "b")])[0] == 100


# ---- DNS signals ----

def test_dns_resolving_or_not():
    assert score_dns(dns_data("104.20.23.154"), NAME)[0] == 40
    assert score_dns({"A": [], "AAAA": [{"value": "2606:4700::1", "ttl": 300}]}, NAME)[0] == 40
    assert score_dns(dns_data(), NAME)[0] == 60


def test_dns_odd_addresses():
    for address in ("127.0.0.1", "10.0.0.1", "192.168.1.1", "0.0.0.0", "169.254.1.1"):
        assert odd_address(address), address
        assert score_dns(dns_data(address), NAME)[0] == 65, address  # 50 - 10 + 25
    assert not odd_address("104.20.23.154") and not odd_address("not an address")


def test_dns_low_ttl_edge():
    assert score_dns(dns_data("104.20.23.154", ttl=59), NAME)[0] == 55  # 50 - 10 + 15
    assert score_dns(dns_data("104.20.23.154", ttl=60), NAME)[0] == 40


def test_name_shape_signals():
    assert name_shape_points("example.com") == []
    assert name_shape_points("xn--bcher-kva.de") == [(10, "punycode label in the name")]  # its "xn--" is not counted as a hyphen
    assert name_shape_points("a1b2c3d4.com") == [(10, "many digits in the name")]
    assert name_shape_points("abcde12fgh.com") == []  # 2 digits of 10 is 20 %, under the 30 % line
    assert name_shape_points("a-b-c.com") == [(5, "two or more hyphens in the name")]
    assert name_shape_points("a-b.com") == []
    assert name_shape_points("a" * 25 + ".com") == [(5, "a very long label in the name")]
    assert name_shape_points("a" * 24 + ".com") == []


def test_name_shape_is_capped_at_20():
    assert name_shape_points("xn--12345-a-b.com") == [(20, "several odd signs in the name shape (capped)")]


# ---- RDAP signals ----

def test_rdap_age_edges():
    cases = {0: 85, 29: 85, 30: 70, 364: 70, 365: 30, 1824: 30, 1825: 10, 10000: 10}
    for days, expected in cases.items():
        assert score_rdap(rdap_data(days), TODAY)[0] == expected, days
    assert score_rdap(rdap_data(None), TODAY)[0] == 50


def test_rdap_hold_status():
    assert score_rdap(rdap_data(5000, ["serverHold"]), TODAY)[0] == 30  # 10 + 20
    assert score_rdap(rdap_data(5000, ["clientHold"]), TODAY)[0] == 30
    assert score_rdap(rdap_data(5000, ["client delete prohibited"]), TODAY)[0] == 10


# ---- crt.sh signals ----

def crt_data(days):
    return {"first_seen": days_ago(days)}


def test_crtsh_age_edges():
    cases = {0: 75, 29: 75, 30: 60, 364: 60, 365: 25, 4000: 25}
    for days, expected in cases.items():
        assert score_crtsh(crt_data(days), TODAY, None)[0] == expected, days


def test_a_crtsh_date_without_a_timezone_works():
    assert score_crtsh({"first_seen": "2020-01-01T00:00:00"}, TODAY, None)[0] == 25


def test_certificate_gap():
    assert score_crtsh(crt_data(5), TODAY, days_ago(400))[0] == 95  # 50 + 25 + 20
    assert score_crtsh(crt_data(5), TODAY, days_ago(364))[0] == 75  # registered under a year ago: no gap
    assert score_crtsh(crt_data(31), TODAY, days_ago(4000))[0] == 60  # first certificate not new: no gap (only the under-1-year +10)
    assert score_crtsh(crt_data(5), TODAY, None)[0] == 75  # RDAP gave no date: no gap


# ---- not found and errors ----

def test_not_found_leans_a_little_and_error_has_no_score():
    scores = {}
    sources = {key: {"status": "not_found", "data": None} for key in ("dns", "rdap", "crtsh")}
    add_scores(sources, NAME, TODAY)
    for key, block in sources.items():
        scores[key] = block["score"]
    assert scores == {"dns": 55, "rdap": 50, "crtsh": 60}
    sources = {"dns": dict(ERROR), "rdap": dict(ERROR), "crtsh": dict(ERROR)}
    assessment = add_scores(sources, NAME, TODAY)
    assert sources["dns"]["score"] is None
    assert assessment["verdict"] == "not_graded" and assessment["average"] is None and assessment["sources_used"] == 0


# ---- the whole assessment ----

def sample_sources():
    return {
        "dns": {"status": "ok", "data": dns_data("104.20.23.154")},  # 40
        "rdap": {"status": "ok", "data": rdap_data(10)},  # 85
        "crtsh": {"status": "ok", "data": crt_data(2000)},  # 25
    }


def test_assessment_with_three_scores():
    sources = sample_sources()
    assessment = add_scores(sources, NAME, TODAY)
    # (40 + 85 + 25) / 3 = 50
    assert assessment == {"score_min": 0, "score_max": 100, "average": 50, "sources_used": 3, "sources_total": 3,
                          "verdict": "undetermined", "verdict_label": "Undetermined", "verdict_note": None}
    assert sources["rdap"]["score"] == 85 and "registered less than 30 days ago (+35)" in sources["rdap"]["score_reason"]


def test_the_certificate_gap_is_found_through_the_rdap_block():
    sources = sample_sources()
    sources["rdap"] = {"status": "ok", "data": rdap_data(2000)}  # 10
    sources["crtsh"] = {"status": "ok", "data": crt_data(5)}  # 50 + 25 + 20
    add_scores(sources, NAME, TODAY)
    assert sources["crtsh"]["score"] == 95


def test_a_failed_source_is_left_out_and_counted():
    sources = sample_sources()
    sources["crtsh"] = dict(ERROR)
    assessment = add_scores(sources, NAME, TODAY)
    assert sources["crtsh"]["score"] is None
    assert assessment["average"] == 63 and assessment["sources_used"] == 2  # (40 + 85) / 2 = 62.5 -> 63
    assert assessment["verdict"] == "likely_malware" and assessment["verdict_note"] is None


def test_all_not_found_is_undetermined():
    sources = {key: {"status": "not_found", "data": None} for key in ("dns", "rdap", "crtsh")}
    assessment = add_scores(sources, NAME, TODAY)
    assert assessment["average"] == 55 and assessment["verdict"] == "undetermined"  # (55 + 50 + 60) / 3


# ---- "definitely" needs all three sources: 3, 2 and 1 sources used, both ends ----

def worst_sources():
    return {
        "dns": {"status": "ok", "data": dns_data("10.0.0.1", ttl=5)},  # 50 - 10 + 25 + 15 = 80
        "rdap": {"status": "ok", "data": rdap_data(5)},  # 85
        "crtsh": {"status": "ok", "data": crt_data(3)},  # 75
    }


def best_sources():
    return {
        "dns": {"status": "ok", "data": dns_data("104.20.23.154")},  # 40
        "rdap": {"status": "ok", "data": rdap_data(5000)},  # 10
        "crtsh": {"status": "ok", "data": crt_data(4000)},  # 25
    }


def test_definitely_malware_needs_all_three_sources():
    three = add_scores(worst_sources(), NAME, TODAY)
    assert three["average"] == 80 and three["verdict"] == "definitely_malware" and three["verdict_note"] is None

    sources = worst_sources()
    sources["crtsh"] = dict(ERROR)
    two = add_scores(sources, NAME, TODAY)
    assert two["average"] == 83 and two["verdict"] == "likely_malware" and "2 of 3" in two["verdict_note"]
    assert two["verdict_label"] == "Likely malware"

    sources = worst_sources()
    sources["dns"], sources["crtsh"] = dict(ERROR), dict(ERROR)
    one = add_scores(sources, NAME, TODAY)
    assert one["average"] == 85 and one["verdict"] == "likely_malware" and "1 of 3" in one["verdict_note"]


def test_definitely_safe_needs_all_three_sources():
    three = add_scores(best_sources(), NAME, TODAY)
    assert three["average"] == 25 and three["verdict"] == "definitely_safe" and three["verdict_note"] is None

    sources = best_sources()
    sources["crtsh"] = dict(ERROR)
    two = add_scores(sources, NAME, TODAY)
    assert two["average"] == 25 and two["verdict"] == "likely_safe" and "2 of 3" in two["verdict_note"]
    assert two["verdict_label"] == "Likely safe"

    sources = best_sources()
    sources["dns"], sources["crtsh"] = dict(ERROR), dict(ERROR)
    one = add_scores(sources, NAME, TODAY)
    assert one["average"] == 10 and one["verdict"] == "likely_safe" and "1 of 3" in one["verdict_note"]


def test_other_verdicts_are_not_changed_by_a_missing_source():
    sources = best_sources()
    sources["rdap"] = {"status": "ok", "data": rdap_data(1000)}  # 30
    sources["crtsh"] = dict(ERROR)
    two = add_scores(sources, NAME, TODAY)  # (40 + 30) / 2 = 35
    assert two["verdict"] == "likely_safe" and two["verdict_note"] is None


def test_scoring_does_not_change_the_original_blocks():
    """Cached results are shared between requests, so scoring must work on copies and leave the originals alone."""
    originals = sample_sources()
    given = {key: block for key, block in originals.items()}
    add_scores(given, NAME, TODAY)
    for block in originals.values():
        assert "score" not in block and "score_reason" not in block
