"""Shared fixtures for Zimbra MCP tests."""

from unittest.mock import MagicMock

import pytest

from zimbra_mcp.client import ZimbraClient
from zimbra_mcp.config import ZimbraConfig


@pytest.fixture
def config():
    """Create a test ZimbraConfig."""
    return ZimbraConfig(
        url="https://zimbra.test/service/soap",
        user="test@example.com",
        password="secret",
        timeout=10,
    )


@pytest.fixture
def connected_client(config):
    """Create a ZimbraClient with mocked connection (no network)."""
    client = ZimbraClient(config)
    client._token = "fake-token"
    client._comm = MagicMock()
    return client


def capture_tools(register_func, client, *extra_args):
    """Capture tool functions registered by a register_*_tools function.

    Returns a dict mapping function names to the actual functions.
    """
    tools = {}
    mock_mcp = MagicMock()

    def capture_tool():
        def decorator(func):
            tools[func.__name__] = func
            return func
        return decorator

    mock_mcp.tool = capture_tool
    register_func(mock_mcp, client, *extra_args)
    return tools
