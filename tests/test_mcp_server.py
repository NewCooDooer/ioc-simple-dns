"""The MCP server, tested against a FAKE backend (no real network). The server only talks to the backend API."""

import pytest
import requests
import responses
from mcp.server.mcpserver.exceptions import ToolError

from mcp_server import server

BACKEND = "http://backend.test:8010"


@pytest.fixture(autouse=True)
def backend_address(monkeypatch):
    monkeypatch.setenv("BACKEND_URL", BACKEND)


def test_lookup_returns_backend_answer_with_cache_ages(mock):
    body = {"ioc": {"type": "domain", "value": "example.com"}, "sources": {"dns": {"status": "ok", "data": {}}}}
    mock.add(responses.GET, BACKEND + "/api/v1/domain/example.com", json=body, headers={"X-Cache-Age-dns": "12"})
    result = server.lookup_domain("  example.com ")
    assert result["ioc"]["value"] == "example.com"
    assert result["cache_age_seconds"] == {"dns": "12"}


def test_lookup_without_cache_headers_has_empty_ages(mock):
    mock.add(responses.GET, BACKEND + "/api/v1/domain/example.com", json={"ioc": {}, "sources": {}})
    assert server.lookup_domain("example.com")["cache_age_seconds"] == {}


def test_invalid_name_is_a_tool_error_with_the_backend_message(mock):
    mock.add(responses.GET, BACKEND + "/api/v1/domain/1.2.3.4", status=400, json={"error": "not a valid DNS name: 1.2.3.4"})
    with pytest.raises(ToolError, match="not a valid DNS name"):
        server.lookup_domain("1.2.3.4")


def test_all_sources_failed_is_returned_as_data(mock):
    body = {"ioc": {}, "sources": {"dns": {"status": "error"}}, "assessment": {"verdict": "not_graded", "average": None}}
    mock.add(responses.GET, BACKEND + "/api/v1/domain/example.com", json=body)
    assert server.lookup_domain("example.com")["assessment"]["verdict"] == "not_graded"


def test_a_status_other_than_200_and_400_is_a_tool_error(mock):
    mock.add(responses.GET, BACKEND + "/api/v1/domain/example.com", status=502, json={"error": "x"})
    with pytest.raises(ToolError, match="unexpected status 502"):
        server.lookup_domain("example.com")


def test_unreachable_backend_is_a_tool_error(mock):
    mock.add(responses.GET, BACKEND + "/api/v1/domain/example.com", body=requests.ConnectionError("refused"))
    with pytest.raises(ToolError, match="Cannot reach"):
        server.lookup_domain("example.com")


def test_missing_backend_url_is_a_tool_error(monkeypatch):
    monkeypatch.delenv("BACKEND_URL")
    with pytest.raises(ToolError, match="BACKEND_URL"):
        server.health()


def test_health(mock):
    mock.add(responses.GET, BACKEND + "/api/v1/health", json={"status": "ok"})
    assert server.health() == {"status": "ok"}
