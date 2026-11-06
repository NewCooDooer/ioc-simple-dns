"""The backend: a small Flask web server.  Start it with:  python -m backend.app"""

import os

from flask import Flask, jsonify

from backend.sources import ask_dns
from backend.validate import check_name

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

    # Step 2: ask the sources. (Milestone 1 has only one. Milestone 2 adds RDAP and crt.sh.)
    sources = {"dns": ask_dns(clean_name)}

    # Step 3: if EVERY source ended in an error, answer 502. Otherwise answer 200 with whatever we have.
    all_failed = True
    for block in sources.values():
        if block["status"] != "error":
            all_failed = False
    if all_failed:
        return error_answer(502, "all sources failed", name, {"sources": sources})

    answer = {
        "ioc": {"type": "domain", "input": name, "value": clean_name},
        "sources": sources,
    }
    return jsonify(answer)


@app.errorhandler(404)
def not_found(problem):
    return error_answer(404, "not found")


@app.errorhandler(500)
def internal_error(problem):
    return error_answer(500, "internal error")


if __name__ == "__main__":
    port = int(os.environ.get("BACKEND_PORT", "8010"))  # read the setting, or use 8010
    app.run(host="127.0.0.1", port=port)
