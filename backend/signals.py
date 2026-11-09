"""The signals behind each source's score. The rules, points and reasons are written in design.md section 4a; change them there first.

Every score starts at 50. Each signal that fires adds points (positive = more malicious, negative = more safe) and a short reason.
"""

import ipaddress
from datetime import date

START = 50
NOT_FOUND_SCORES = {"dns": 55, "rdap": 50, "crtsh": 60}  # a slight lean towards risk for DNS and crt.sh (design.md 4a)


def age_in_days(text, today):
    """How many days ago a date like "1995-08-14T04:00:00Z" was. Only the first 10 characters (the day) are used."""
    return (today - date.fromisoformat(text[:10])).days


def finish(points):
    """Turn a list of (points, reason) into (score, reason text). The score is kept between 0 and 100."""
    score = START
    reasons = []
    for amount, reason in points:
        score += amount
        reasons.append(f"{reason} ({amount:+d})")
    score = max(0, min(100, score))
    return score, "; ".join(reasons) if reasons else "no signal fired"


def odd_address(text):
    """True for an address a real public site does not use: loopback, private, link-local, reserved or all zeros."""
    try:
        address = ipaddress.ip_address(text)
    except ValueError:
        return False
    return address.is_loopback or address.is_private or address.is_link_local or address.is_reserved or address.is_unspecified


def name_shape_points(name):
    """Points for how the name itself looks (at most +20): punycode, many digits, many hyphens, a very long label."""
    points = []
    labels = name.split(".")
    if any(label.startswith("xn--") for label in labels):
        points.append((10, "punycode label in the name"))
    first = labels[0]
    if len(first) > 0 and sum(ch.isdigit() for ch in first) / len(first) > 0.3:
        points.append((10, "many digits in the name"))
    if name.replace("xn--", "").count("-") >= 2:  # the "xn--" of a punycode label is not a real hyphen
        points.append((5, "two or more hyphens in the name"))
    if max(len(label) for label in labels) >= 25:
        points.append((5, "a very long label in the name"))
    if sum(amount for amount, reason in points) > 20:
        points = [(20, "several odd signs in the name shape (capped)")]
    return points


def score_dns(data, name):
    """DNS: does it resolve, to what kind of address, with what TTL, and what does the name look like."""
    records = data["A"] + data["AAAA"]
    points = []
    if len(records) > 0:
        points.append((-10, "resolves to an address"))
    else:
        points.append((10, "no A or AAAA record"))
    if any(odd_address(record["value"]) for record in records):
        points.append((25, "points to a loopback, private or reserved address"))
    if len(records) > 0 and min(record["ttl"] for record in records) < 60:
        points.append((15, "very low TTL"))
    points += name_shape_points(name)
    return finish(points)


def score_rdap(data, today):
    """RDAP: how long ago was the name registered, and has it been put on hold."""
    points = []
    if data["registered"]:
        days = age_in_days(data["registered"], today)
        if days < 30:
            points.append((35, "registered less than 30 days ago"))
        elif days < 365:
            points.append((10, "registered less than 1 year ago"))
        elif days < 5 * 365:
            points.append((-20, "registered 1 to 5 years ago"))
        else:
            points.append((-40, "registered 5 years or more ago"))
    else:
        points.append((0, "no registration date"))
    if any("hold" in status.lower() for status in data["statuses"]):
        points.append((20, "a hold status"))
    return finish(points)


def score_crtsh(data, today, registered):
    """crt.sh: how old is the first certificate, and does a long-registered name suddenly have a brand-new certificate.

    `registered` is the RDAP registration date text, or None if RDAP gave none.
    """
    points = []
    days = age_in_days(data["first_seen"], today)
    if days < 30:
        points.append((25, "first certificate issued less than 30 days ago"))
    elif days < 365:
        points.append((0, "first certificate issued less than 1 year ago"))
    else:
        points.append((-25, "first certificate issued 1 year or more ago"))
    if registered and age_in_days(registered, today) >= 365 and days < 30:
        points.append((20, "registered long ago but the first certificate is new"))
    return finish(points)
