"""Turns each source's result into a score from 0 to 100, then into one verdict.

0 = definitely malware, 100 = definitely not malware. These are rough guesses from weak signals, not findings.
The rules and their reasons are written in design.md section 4a; change them there first.
"""

from datetime import date

MIN_SCORE = 0
MAX_SCORE = 100
NEUTRAL_SCORE = 50  # used when a source answered "not found"


def age_in_days(text, today):
    """How many days ago a date like "1995-08-14T04:00:00Z" was. Only the first 10 characters (the day) are used."""
    return (today - date.fromisoformat(text[:10])).days


def score_dns(data):
    """Score Google DNS data: a name that points to an address is a little more normal than one that points nowhere."""
    if len(data["A"]) > 0 or len(data["AAAA"]) > 0:
        return 60, "the name resolves to an address"
    return 40, "the name exists but has no A or AAAA record"


def score_rdap(data, today):
    """Score RDAP data by how long ago the name was registered: newly registered names are a classic warning sign."""
    if not data["registered"]:
        return 50, "no registration date to judge by"
    days = age_in_days(data["registered"], today)
    if days < 30:
        return 15, "registered less than 30 days ago"
    if days < 365:
        return 40, "registered less than 1 year ago"
    if days < 5 * 365:
        return 70, "registered 1 to 5 years ago"
    return 90, "registered 5 years or more ago"


def score_crtsh(data, today):
    """Score crt.sh data by the age of the first certificate: a long certificate history suggests an established site."""
    days = age_in_days(data["first_seen"], today)
    if days < 30:
        return 25, "first certificate issued less than 30 days ago"
    if days < 365:
        return 50, "first certificate issued less than 1 year ago"
    return 75, "first certificate issued 1 year or more ago"


def score_source(key, block, today):
    """Score one source block. Returns (score, reason); the score is None when the source had an error."""
    if block["status"] == "error":
        return None, "no score: the source could not be reached, so it is left out of the average"
    if block["status"] == "not_found":
        return NEUTRAL_SCORE, "the source knows nothing about this name, which is neutral"
    if key == "dns":
        return score_dns(block["data"])
    if key == "rdap":
        return score_rdap(block["data"], today)
    return score_crtsh(block["data"], today)


def average_of(scores):
    """Average of the scores that exist (None is skipped), rounded to a whole number with .5 rounding up.

    Returns (average, how many scores were used). The average is None if there were none.
    """
    used = []
    for score in scores:
        if score is not None:
            used.append(score)
    if len(used) == 0:
        return None, 0
    return int(sum(used) / len(used) + 0.5), len(used)


def verdict_for(average):
    """Turn an average (0 to 100) into (code, label). Bands: 0-40, 41-60, 61-100."""
    if average <= 40:
        return "likely_malware", "Likely malware"
    if average <= 60:
        return "undetermined", "Undetermined"
    return "likely_safe", "Likely safe"


def add_scores(sources, today):
    """Add "score" and "score_reason" to every source block, and return the "assessment" dictionary.

    Returns None when no source produced a score (every source had an error); the caller answers 502 in that case.
    """
    scores = []
    for key, block in sources.items():
        block["score"], block["score_reason"] = score_source(key, block, today)
        scores.append(block["score"])

    average, used = average_of(scores)
    if average is None:
        return None
    code, label = verdict_for(average)

    # A firm verdict needs ALL sources. With fewer, a flaky source could flip the verdict between runs, so cap it at undetermined.
    note = None
    if used < len(sources):
        code, label = "undetermined", "Undetermined"
        note = f"only {used} of {len(sources)} sources gave a score, so the verdict cannot be more than Undetermined"
    return {
        "score_min": MIN_SCORE,
        "score_max": MAX_SCORE,
        "average": average,
        "sources_used": used,
        "sources_total": len(sources),
        "verdict": code,
        "verdict_label": label,
        "verdict_note": note,
    }
