"""Proof that the test suite runs with the network off: pytest-socket blocks every real connection."""

import socket

import pytest
from pytest_socket import SocketBlockedError


def test_real_network_connections_are_blocked():
    with pytest.raises(SocketBlockedError):
        socket.create_connection(("example.com", 80), timeout=2)
