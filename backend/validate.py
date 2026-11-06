"""Checks that what the user typed is an acceptable DNS name, and cleans it up."""

import ipaddress

# The only characters allowed inside one piece of a name (the part between dots).
ALLOWED_CHARACTERS = "abcdefghijklmnopqrstuvwxyz0123456789-_"

# Characters that must never appear in a name. If one is there, someone probably pasted a URL or an e-mail address.
FORBIDDEN_CHARACTERS = "/:@?# \t\r\n"


def check_name(raw):
    """Return the cleaned-up name, or raise ValueError with the reason it is not acceptable."""
    # Step 1: tidy up. Remove spaces at the ends, drop one trailing dot, make it lowercase.
    name = raw.strip()
    if name.endswith("."):
        name = name[:-1]  # [:-1] means "everything except the last character"
    name = name.lower()
    if name == "":
        raise ValueError("empty input")

    # Step 2: reject things that are not domain names.
    if looks_like_an_ip_address(name):
        raise ValueError("IP addresses are not accepted")
    for character in name:
        if character in FORBIDDEN_CHARACTERS:
            raise ValueError("URLs, ports, e-mail addresses and spaces are not accepted")

    # Step 3: convert non-English letters into plain letters called punycode (bücher.de becomes xn--bcher-kva.de).
    try:
        name = name.encode("idna").decode("ascii")
    except UnicodeError:
        raise ValueError("invalid name (it could not be converted to plain letters)")

    # Step 4: check the size and shape of the name.
    if len(name) > 253:
        raise ValueError("longer than 253 characters")

    labels = name.split(".")  # "login.example.com" becomes ["login", "example", "com"]
    if len(labels) < 2:
        raise ValueError("a single word is not a DNS name to look up")
    for label in labels:
        check_label(label)
    if labels[-1].isdigit():  # labels[-1] is the last piece, like "com"
        raise ValueError("the last part cannot be all digits")

    return name


def looks_like_an_ip_address(text):
    """True for things like 10.0.0.1 or 2001:db8::1."""
    try:
        ipaddress.ip_address(text)  # raises ValueError if the text is NOT an IP address
    except ValueError:
        return False
    return True


def check_label(label):
    """Check one piece of a name (the part between dots). Raise ValueError if it is not acceptable."""
    if label == "" or len(label) > 63:
        raise ValueError(f"invalid part: {label!r} (empty or longer than 63 characters)")
    if label.startswith("-") or label.endswith("-"):
        raise ValueError(f"invalid part: {label!r} (cannot start or end with a hyphen)")
    for character in label:
        if character not in ALLOWED_CHARACTERS:
            raise ValueError(f"invalid part: {label!r} (contains {character!r})")
