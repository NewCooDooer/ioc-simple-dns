"""The name checker: which names are accepted, cleaned, or refused. No network involved."""

import pytest

from backend.validate import check_name


@pytest.mark.parametrize(
    "typed, expected",
    [
        ("example.com", "example.com"),
        ("Example.COM", "example.com"),
        ("  example.com. ", "example.com"),
        ("login.example.com", "login.example.com"),
        ("_dmarc.example.com", "_dmarc.example.com"),
        ("bücher.de", "xn--bcher-kva.de"),
        ("xn--bcher-kva.de", "xn--bcher-kva.de"),
    ],
)
def test_good_names_are_cleaned(typed, expected):
    assert check_name(typed) == expected


@pytest.mark.parametrize(
    "typed",
    [
        "",
        "   ",
        "10.0.0.1",
        "2001:db8::1",
        "localhost",
        "https://example.com",
        "user@example.com",
        "example.com:8080",
        "not a name",
        "-bad.example.com",
        "bad-.example.com",
        "a..b.com",
        "exa$mple.com",
        "example.123",
        "a" * 64 + ".com",
        ".".join(["a" * 60] * 5) + ".com",
    ],
)
def test_bad_names_are_refused(typed):
    with pytest.raises(ValueError):
        check_name(typed)


def test_the_reason_is_in_the_error_message():
    with pytest.raises(ValueError, match="IP addresses are not accepted"):
        check_name("10.0.0.1")
