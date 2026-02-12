"""Tests for ZimbraClient."""

from unittest.mock import MagicMock, patch

import pytest

from zimbra_mcp.client import ZimbraClient
from zimbra_mcp.config import ZimbraConfig
from zimbra_mcp.errors import (
    ZimbraAuthError,
    ZimbraConnectionError,
    ZimbraNotFoundError,
    ZimbraOperationError,
)


@pytest.fixture
def client(config):
    return ZimbraClient(config)


class TestConnection:
    @patch("zimbra_mcp.client.auth.authenticate", return_value="tok123")
    @patch("zimbra_mcp.client.Communication")
    def test_connect_success(self, mock_comm_cls, mock_auth, client):
        client.connect()
        assert client.is_connected
        assert client._token == "tok123"
        mock_comm_cls.assert_called_once_with(client.config.url)

    @patch("zimbra_mcp.client.auth.authenticate", return_value=None)
    @patch("zimbra_mcp.client.Communication")
    def test_connect_auth_failure(self, mock_comm_cls, mock_auth, client):
        with pytest.raises(ZimbraAuthError):
            client.connect()

    @patch("zimbra_mcp.client.auth.authenticate", side_effect=Exception("network"))
    @patch("zimbra_mcp.client.Communication")
    def test_connect_network_failure(self, mock_comm_cls, mock_auth, client):
        with pytest.raises(ZimbraConnectionError, match="network"):
            client.connect()

    def test_disconnect(self, connected_client):
        connected_client.disconnect()
        assert not connected_client.is_connected
        assert connected_client._comm is None


class TestRequest:
    def test_request_success(self, connected_client):
        mock_response = MagicMock()
        mock_response.is_fault.return_value = False
        mock_response.get_response.return_value = {"TestResponse": {"data": "ok"}}

        mock_request = MagicMock()
        connected_client._comm.gen_request.return_value = mock_request
        connected_client._comm.send_request.return_value = mock_response

        result = connected_client.request("TestRequest", "urn:test", {"key": "val"})

        assert result == {"data": "ok"}
        mock_request.add_request.assert_called_once_with("TestRequest", {"key": "val"}, "urn:test")

    def test_request_fault_not_found(self, connected_client):
        mock_response = MagicMock()
        mock_response.is_fault.return_value = True
        mock_response.get_response.return_value = {
            "Fault": {"Reason": {"Text": "no such message"}}
        }

        connected_client._comm.gen_request.return_value = MagicMock()
        connected_client._comm.send_request.return_value = mock_response

        with pytest.raises(ZimbraNotFoundError, match="no such message"):
            connected_client.request("GetMsgRequest", "urn:zimbraMail")

    def test_request_fault_operation_error(self, connected_client):
        mock_response = MagicMock()
        mock_response.is_fault.return_value = True
        mock_response.get_response.return_value = {
            "Fault": {"Reason": {"Text": "invalid request"}}
        }

        connected_client._comm.gen_request.return_value = MagicMock()
        connected_client._comm.send_request.return_value = mock_response

        with pytest.raises(ZimbraOperationError, match="invalid request"):
            connected_client.request("BadRequest", "urn:zimbraMail")

    def test_request_not_connected_triggers_connect(self, config):
        client = ZimbraClient(config)
        with patch.object(client, "connect") as mock_connect:
            mock_connect.side_effect = ZimbraConnectionError("no server")
            with pytest.raises(ZimbraConnectionError):
                client.request("TestRequest", "urn:test")


class TestDeleteMessages:
    def test_soft_delete(self, connected_client):
        mock_response = MagicMock()
        mock_response.is_fault.return_value = False
        mock_response.get_response.return_value = {
            "MsgActionResponse": {"action": {"id": "1,2", "op": "trash"}}
        }

        connected_client._comm.gen_request.return_value = MagicMock()
        connected_client._comm.send_request.return_value = mock_response

        result = connected_client.delete_messages(["1", "2"])

        call_args = connected_client._comm.gen_request.return_value.add_request.call_args
        params = call_args[0][1]
        assert params["action"]["op"] == "trash"
        assert params["action"]["id"] == "1,2"

    def test_hard_delete(self, connected_client):
        mock_response = MagicMock()
        mock_response.is_fault.return_value = False
        mock_response.get_response.return_value = {
            "MsgActionResponse": {"action": {"id": "5", "op": "delete"}}
        }

        connected_client._comm.gen_request.return_value = MagicMock()
        connected_client._comm.send_request.return_value = mock_response

        result = connected_client.delete_messages(["5"], hard_delete=True)

        call_args = connected_client._comm.gen_request.return_value.add_request.call_args
        params = call_args[0][1]
        assert params["action"]["op"] == "delete"


class TestSendMessage:
    def test_send_basic(self, connected_client):
        mock_response = MagicMock()
        mock_response.is_fault.return_value = False
        mock_response.get_response.return_value = {
            "SendMsgResponse": {"m": {"id": "100"}}
        }

        connected_client._comm.gen_request.return_value = MagicMock()
        connected_client._comm.send_request.return_value = mock_response

        result = connected_client.send_message(
            to=["bob@test.com"], subject="Hi", body="Hello",
        )

        call_args = connected_client._comm.gen_request.return_value.add_request.call_args
        assert call_args[0][0] == "SendMsgRequest"
        assert call_args[0][2] == "urn:zimbraMail"
        params = call_args[0][1]
        assert params["m"]["su"] == "Hi"
        assert params["m"]["mp"]["content"] == "Hello"

    def test_send_with_draft_id(self, connected_client):
        mock_response = MagicMock()
        mock_response.is_fault.return_value = False
        mock_response.get_response.return_value = {
            "SendMsgResponse": {"m": {"id": "101"}}
        }

        connected_client._comm.gen_request.return_value = MagicMock()
        connected_client._comm.send_request.return_value = mock_response

        result = connected_client.send_message(
            to=["bob@test.com"], subject="Hi", body="Hello", draft_id="50",
        )

        call_args = connected_client._comm.gen_request.return_value.add_request.call_args
        params = call_args[0][1]
        assert params["m"]["did"] == "50"
