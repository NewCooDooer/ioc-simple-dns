"""The backend: a small Flask web server.  Start it with:  python -m backend.app"""

import os
from datetime import datetime, timezone

from flask import Flask, jsonify

from backend.scoring import add_scores
from backend.sources import ask_crtsh, ask_dns, ask_rdap
from backend.validate import check_name

MIN_ANSWERS = 2  # at least this many of the three sources must answer, otherwise we do not grade (design.md section 4)

app = Flask(__name__)
app.json.sort_keys = False  # keep the answer's fields in the order we wrote them


def error_answer(status_code, message, typed_name=None, extra=None):
    """Build the ONE error format used everywhere: {"error": "...", "input": "..."}."""
    body = {"error": message}
    if typed_name is not None:
        body["input"] = typed_name
    if extra is not None:
        body.update(extra)
    return jsonify(body), status_code


# "@app.route(...)" is a decorator: it says "when someone requests this address, run the function below".
@app.route("/api/v1/health")
def health():
    return jsonify({"status": "ok"})


@app.route("/api/v1/domain/<path:name>")
def domain(name):
    # Step 1: check the name. A bad name stops here with a 400 and no outside service is contacted.
    try:
        clean_name = check_name(name)
    except ValueError as problem:
        return error_answer(400, f"not a valid DNS name: {name} ({problem})", name)

    # Step 2: ask the three sources, one after another, in the order they are written here.
    # (Each ask_... function never crashes: a problem comes back as an error result.)
    # Each ask_... returns TWO things: the result, and its age in seconds if it came from the cache (None if fresh).
    dns, dns_age = ask_dns(clean_name)
    rdap, rdap_age = ask_rdap(clean_name)
    crtsh, crtsh_age = ask_crtsh(clean_name)
    sources = {"dns": dns, "rdap": rdap, "crtsh": crtsh}
    ages = {"dns": dns_age, "rdap": rdap_age, "crtsh": crtsh_age}

    # Step 3: count the sources that ANSWERED (ok or not_found; an error is not an answer).
    # If fewer than MIN_ANSWERS answered there is nothing reliable to grade, so answer 502. The source blocks still go
    # along, so the facts of a source that did answer are not lost.
    answered = 0
    for block in sources.values():
        if block["status"] != "error":
            answered += 1
    if answered < MIN_ANSWERS:
        return error_answer(502, f"too few sources answered: at least {MIN_ANSWERS} of {len(sources)} must answer", name, {"sources": sources})

    # Step 4: score each source, average the scores and pick a verdict (the sources dictionary gets "score" fields added).
    answer = {
        "ioc": {"type": "domain", "input": name, "value": clean_name},
        "sources": sources,
        "assessment": add_scores(sources, clean_name, datetime.now(timezone.utc).date()),
    }
    response = jsonify(answer)

    # Step 4: say which sources came from the cache. The body stays exactly as the sources gave it; the news goes in
    # headers, one per cached source, for example  X-Cache-Age-rdap: 412  (fetched 412 s ago).
    # A source with no such header was just fetched. (An error is never cached, so it never gets one.)
    for key, age in ages.items():
        if age is not None:
            response.headers[f"X-Cache-Age-{key}"] = str(age)
    return response


@app.errorhandler(404)
def not_found(problem):
    return error_answer(404, "not found")


@app.errorhandler(500)
def internal_error(problem):
    return error_answer(500, "internal error")


if __name__ == "__main__":
    port = int(os.environ.get("BACKEND_PORT", "8010"))  # read the setting, or use 8010
    app.run(host="127.0.0.1", port=port)
