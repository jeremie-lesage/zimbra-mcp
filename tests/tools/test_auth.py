"""Tests for authentication tools."""

import pytest

from tests.conftest import capture_tools
from zimbra_mcp.tools.auth import register_auth_tools


@pytest.fixture
def auth_tools(connected_client):
    tools = capture_tools(register_auth_tools, connected_client)
    return tools, connected_client


class TestAuthenticate:
    def test_authenticate_passes_code_to_client(self, auth_tools):
        tools, client = auth_tools
        client.authenticate = lambda totp_code=None: setattr(client, "_seen_code", totp_code)
        result = tools["zimbra_authenticate"](code="  123456  ")
        # Code is trimmed before being handed to the client.
        assert client._seen_code == "123456"
        assert result["status"] == "authenticated"
        assert result["user"] == client.config.user

    def test_auth_status_reflects_connection(self, auth_tools):
        tools, client = auth_tools
        assert tools["zimbra_auth_status"]()["authenticated"] is True
        client.disconnect()
        assert tools["zimbra_auth_status"]()["authenticated"] is False
