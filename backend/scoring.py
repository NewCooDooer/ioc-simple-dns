"""Turns each source's result into a score from 0 to 100, then into one verdict.

0 = definitely safe, 100 = definitely malware. These are rough guesses from weak signals, not findings.
The signals, their points and their reasons are in signals.py; the verdict bands are in verdict_for below.
"""

from backend.signals import NOT_FOUND_SCORES, score_crtsh, score_dns, score_rdap

MIN_SCORE = 0
MAX_SCORE = 100


def score_source(key, block, name, today, registered):
    """Score one source block. Returns (score, reason); the score is None when the source had an error.

    `registered` is the RDAP registration date text (or None); only the crt.sh score uses it.
    """
    if block["status"] == "error":
        return None, "no score: the source could not be reached, so it is left out of the average"
    if block["status"] == "not_found":
        return NOT_FOUND_SCORES[key], "the source knows nothing about this name"
    if key == "dns":
        return score_dns(block["data"], name)
    if key == "rdap":
        return score_rdap(block["data"], today)
    return score_crtsh(block["data"], today, registered)


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
    """Turn an average (0 to 100) into (code, label). Bands: 0-30, 31-45, 46-55, 56-70, 71-100."""
    if average <= 30:
        return "definitely_safe", "Definitely safe"
    if average <= 45:
        return "likely_safe", "Likely safe"
    if average <= 55:
        return "undetermined", "Undetermined"
    if average <= 70:
        return "likely_malware", "Likely malware"
    return "definitely_malware", "Definitely malware"


def add_scores(sources, name, today):
    """Add "score" and "score_reason" to every source block, and return the "assessment" dictionary.

    When no source produced a score (every source had an error) the assessment says "not_graded": no average, no verdict.
    """
    # The certificate-gap signal needs RDAP's registration date, so find it first.
    registered = None
    rdap = sources.get("rdap")
    if rdap is not None and rdap["status"] == "ok":
        registered = rdap["data"]["registered"]

    scores = []
    for key, block in sources.items():
        # Work on a copy: a cached result is shared between requests, so it must never be changed.
        block = dict(block)
        block["score"], block["score_reason"] = score_source(key, block, name, today, registered)
        sources[key] = block
        scores.append(block["score"])

    average, used = average_of(scores)
    if average is None:
        return {
            "score_min": MIN_SCORE,
            "score_max": MAX_SCORE,
            "average": None,
            "sources_used": 0,
            "sources_total": len(sources),
            "verdict": "not_graded",
            "verdict_label": "Not graded",
            "verdict_note": "no source answered, so there is no verdict",
        }
    code, label = verdict_for(average)

    # "Definitely" needs ALL sources. With fewer, lower it one step to the matching "likely" and say why.
    note = None
    if used < len(sources) and code.startswith("definitely_"):
        code = code.replace("definitely_", "likely_")
        label = "Likely " + code[len("likely_"):]
        note = f"only {used} of {len(sources)} sources gave a score, so the verdict cannot be 'definitely'"
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
