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


def _make_ok_response(response_name, data):
    """Create a mock response that returns data under response_name."""
    mock_response = MagicMock()
    mock_response.is_fault.return_value = False
    mock_response.get_response.return_value = {response_name: data}
    return mock_response


def _setup_response(connected_client, response):
    """Wire a mock response into a connected client."""
    connected_client._comm.gen_request.return_value = MagicMock()
    connected_client._comm.send_request.return_value = response


def _get_request_params(connected_client):
    """Extract the params dict from the last add_request call."""
    call_args = connected_client._comm.gen_request.return_value.add_request.call_args
    return call_args[0][1]


# --- Connection tests ---


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

    def test_is_connected_default_false(self, config):
        c = ZimbraClient(config)
        assert not c.is_connected


class TestRequest:
    def test_request_success(self, connected_client):
        resp = _make_ok_response("TestResponse", {"data": "ok"})
        _setup_response(connected_client, resp)

        result = connected_client.request("TestRequest", "urn:test", {"key": "val"})

        assert result == {"data": "ok"}
        mock_request = connected_client._comm.gen_request.return_value
        mock_request.add_request.assert_called_once_with("TestRequest", {"key": "val"}, "urn:test")

    def test_request_no_params(self, connected_client):
        resp = _make_ok_response("TestResponse", {})
        _setup_response(connected_client, resp)

        connected_client.request("TestRequest", "urn:test")
        params = _get_request_params(connected_client)
        assert params == {}

    def test_request_fault_not_found(self, connected_client):
        mock_response = MagicMock()
        mock_response.is_fault.return_value = True
        mock_response.get_response.return_value = {
            "Fault": {"Reason": {"Text": "no such message"}}
        }
        _setup_response(connected_client, mock_response)

        with pytest.raises(ZimbraNotFoundError, match="no such message"):
            connected_client.request("GetMsgRequest", "urn:zimbraMail")

    def test_request_fault_operation_error(self, connected_client):
        mock_response = MagicMock()
        mock_response.is_fault.return_value = True
        mock_response.get_response.return_value = {
            "Fault": {"Reason": {"Text": "invalid request"}}
        }
        _setup_response(connected_client, mock_response)

        with pytest.raises(ZimbraOperationError, match="invalid request"):
            connected_client.request("BadRequest", "urn:zimbraMail")

    def test_request_not_connected_triggers_connect(self, config):
        client = ZimbraClient(config)
        with patch.object(client, "connect") as mock_connect:
            mock_connect.side_effect = ZimbraConnectionError("no server")
            with pytest.raises(ZimbraConnectionError):
                client.request("TestRequest", "urn:test")

    def test_request_exception_wrapped(self, connected_client):
        connected_client._comm.gen_request.side_effect = RuntimeError("boom")
        with pytest.raises(ZimbraOperationError, match="boom"):
            connected_client.request("TestRequest", "urn:test")


# --- Mail methods ---


class TestSearchMessages:
    def test_params(self, connected_client):
        resp = _make_ok_response("SearchResponse", {"m": []})
        _setup_response(connected_client, resp)

        connected_client.search_messages("in:inbox", limit=10, offset=5)
        params = _get_request_params(connected_client)
        assert params["query"] == "in:inbox"
        assert params["limit"] == 10
        assert params["offset"] == 5
        assert params["types"] == "message"
        assert params["fetch"] == "all"


class TestGetMessage:
    def test_params(self, connected_client):
        resp = _make_ok_response("GetMsgResponse", {"m": {}})
        _setup_response(connected_client, resp)

        connected_client.get_message("42", raw=True)
        params = _get_request_params(connected_client)
        assert params["m"]["id"] == "42"
        assert params["m"]["raw"] == 1


class TestGetFolder:
    def test_params(self, connected_client):
        resp = _make_ok_response("GetFolderResponse", {"folder": {}})
        _setup_response(connected_client, resp)

        connected_client.get_folder("/Inbox")
        params = _get_request_params(connected_client)
        assert params["folder"]["path"] == "/Inbox"


class TestMoveMessages:
    def test_params(self, connected_client):
        resp = _make_ok_response("MsgActionResponse", {"action": {}})
        _setup_response(connected_client, resp)

        connected_client.move_messages(["1", "2"], "5")
        params = _get_request_params(connected_client)
        assert params["action"]["id"] == "1,2"
        assert params["action"]["op"] == "move"
        assert params["action"]["l"] == "5"


class TestMarkAsRead:
    def test_read(self, connected_client):
        resp = _make_ok_response("MsgActionResponse", {"action": {}})
        _setup_response(connected_client, resp)

        connected_client.mark_as_read(["1"], read=True)
        params = _get_request_params(connected_client)
        assert params["action"]["op"] == "read"

    def test_unread(self, connected_client):
        resp = _make_ok_response("MsgActionResponse", {"action": {}})
        _setup_response(connected_client, resp)

        connected_client.mark_as_read(["1"], read=False)
        params = _get_request_params(connected_client)
        assert params["action"]["op"] == "!read"


class TestDeleteMessages:
    def test_soft_delete(self, connected_client):
        resp = _make_ok_response("MsgActionResponse", {"action": {}})
        _setup_response(connected_client, resp)

        connected_client.delete_messages(["1", "2"])
        params = _get_request_params(connected_client)
        assert params["action"]["op"] == "trash"
        assert params["action"]["id"] == "1,2"

    def test_hard_delete(self, connected_client):
        resp = _make_ok_response("MsgActionResponse", {"action": {}})
        _setup_response(connected_client, resp)

        connected_client.delete_messages(["5"], hard_delete=True)
        params = _get_request_params(connected_client)
        assert params["action"]["op"] == "delete"


class TestCreateDraft:
    def test_basic_draft(self, connected_client):
        resp = _make_ok_response("SaveDraftResponse", {"m": {"id": "50"}})
        _setup_response(connected_client, resp)

        connected_client.create_draft(
            to=["bob@test.com"], subject="Hello", body="Hi Bob",
        )
        params = _get_request_params(connected_client)
        assert params["m"]["su"] == "Hello"
        assert params["m"]["mp"]["content"] == "Hi Bob"
        # Check sender address
        sender = [e for e in params["m"]["e"] if e["t"] == "f"]
        assert len(sender) == 1
        assert sender[0]["a"] == "test@example.com"

    def test_draft_with_cc_bcc(self, connected_client):
        resp = _make_ok_response("SaveDraftResponse", {"m": {"id": "51"}})
        _setup_response(connected_client, resp)

        connected_client.create_draft(
            to=["bob@test.com"], subject="Hi", body="Hey",
            cc=["cc@test.com"], bcc=["bcc@test.com"],
        )
        params = _get_request_params(connected_client)
        types = {e["t"] for e in params["m"]["e"]}
        assert "c" in types
        assert "b" in types

    def test_draft_reply(self, connected_client):
        resp = _make_ok_response("SaveDraftResponse", {"m": {"id": "52"}})
        _setup_response(connected_client, resp)

        connected_client.create_draft(
            to=["bob@test.com"], subject="Re: Hi", body="Thanks",
            orig_msg_id="10", reply_type="r",
        )
        params = _get_request_params(connected_client)
        assert params["m"]["origid"] == "10"
        assert params["m"]["rt"] == "r"

    def test_draft_with_attachment(self, connected_client):
        resp = _make_ok_response("SaveDraftResponse", {"m": {"id": "53"}})
        _setup_response(connected_client, resp)

        connected_client.create_draft(
            to=["bob@test.com"], subject="Fwd", body="See attached",
            attach_msg_id="20",
        )
        params = _get_request_params(connected_client)
        assert params["m"]["attach"]["m"]["id"] == "20"


class TestSendMessage:
    def test_send_basic(self, connected_client):
        resp = _make_ok_response("SendMsgResponse", {"m": {"id": "100"}})
        _setup_response(connected_client, resp)

        connected_client.send_message(to=["bob@test.com"], subject="Hi", body="Hello")

        call_args = connected_client._comm.gen_request.return_value.add_request.call_args
        assert call_args[0][0] == "SendMsgRequest"
        assert call_args[0][2] == "urn:zimbraMail"
        params = call_args[0][1]
        assert params["m"]["su"] == "Hi"

    def test_send_with_draft_id(self, connected_client):
        resp = _make_ok_response("SendMsgResponse", {"m": {"id": "101"}})
        _setup_response(connected_client, resp)

        connected_client.send_message(
            to=["bob@test.com"], subject="Hi", body="Hello", draft_id="50",
        )
        params = _get_request_params(connected_client)
        assert params["m"]["did"] == "50"

    def test_send_reply(self, connected_client):
        resp = _make_ok_response("SendMsgResponse", {"m": {"id": "102"}})
        _setup_response(connected_client, resp)

        connected_client.send_message(
            to=["bob@test.com"], subject="Re: Hi", body="Thanks",
            orig_msg_id="10", reply_type="r",
        )
        params = _get_request_params(connected_client)
        assert params["m"]["origid"] == "10"
        assert params["m"]["rt"] == "r"


# --- Attachment download ---


def _mock_urlopen_response(content=b"data", headers=None):
    """Build a context-manager mock mimicking urllib's response object."""
    default_headers = {
        "Content-Type": "application/pdf",
        "Content-Disposition": 'attachment; filename="report.pdf"',
    }
    default_headers.update(headers or {})

    resp = MagicMock()
    resp.read.return_value = content
    resp.headers.get.side_effect = lambda key, default=None: default_headers.get(key, default)
    cm = MagicMock()
    cm.__enter__.return_value = resp
    cm.__exit__.return_value = False
    return cm, resp


class TestGetAttachmentContent:
    def test_rejects_oversized_via_content_length(self, connected_client):
        from zimbra_mcp.client import MAX_ATTACHMENT_SIZE_BYTES

        cm, _ = _mock_urlopen_response(
            headers={"Content-Length": str(MAX_ATTACHMENT_SIZE_BYTES + 1)}
        )
        with patch("urllib.request.urlopen", return_value=cm), \
             patch("urllib.request.Request"):
            with pytest.raises(ZimbraOperationError, match="too large"):
                connected_client.get_attachment_content("5", "2")

    def test_rejects_oversized_when_body_exceeds_cap(self, connected_client):
        from zimbra_mcp.client import MAX_ATTACHMENT_SIZE_BYTES

        # No/honest Content-Length, but the body itself overflows the cap.
        cm, resp = _mock_urlopen_response(content=b"x" * (MAX_ATTACHMENT_SIZE_BYTES + 1))
        with patch("urllib.request.urlopen", return_value=cm), \
             patch("urllib.request.Request"):
            with pytest.raises(ZimbraOperationError, match="too large"):
                connected_client.get_attachment_content("5", "2")
        # The read must be bounded, not unbounded.
        resp.read.assert_called_once_with(MAX_ATTACHMENT_SIZE_BYTES + 1)


# --- Tag methods ---


class TestGetAllTags:
    def test_call(self, connected_client):
        resp = _make_ok_response("GetTagResponse", {"tag": []})
        _setup_response(connected_client, resp)

        result = connected_client.get_all_tags()
        call_args = connected_client._comm.gen_request.return_value.add_request.call_args
        assert call_args[0][0] == "GetTagRequest"


class TestCreateTag:
    def test_with_color(self, connected_client):
        resp = _make_ok_response("CreateTagResponse", {"tag": {"id": "1"}})
        _setup_response(connected_client, resp)

        connected_client.create_tag("urgent", color=5)
        params = _get_request_params(connected_client)
        assert params["tag"]["name"] == "urgent"
        assert params["tag"]["color"] == 5


class TestDeleteTag:
    def test_call(self, connected_client):
        resp = _make_ok_response("TagActionResponse", {"action": {}})
        _setup_response(connected_client, resp)

        connected_client.delete_tag("3")
        params = _get_request_params(connected_client)
        assert params["action"]["op"] == "delete"
        assert params["action"]["id"] == "3"


class TestTagMessages:
    def test_tag(self, connected_client):
        resp = _make_ok_response("MsgActionResponse", {"action": {}})
        _setup_response(connected_client, resp)

        connected_client.tag_messages(["1", "2"], "work")
        params = _get_request_params(connected_client)
        assert params["action"]["op"] == "tag"
        assert params["action"]["tn"] == "work"

    def test_untag(self, connected_client):
        resp = _make_ok_response("MsgActionResponse", {"action": {}})
        _setup_response(connected_client, resp)

        connected_client.tag_messages(["1"], "old", untag=True)
        params = _get_request_params(connected_client)
        assert params["action"]["op"] == "!tag"


# --- Calendar methods ---


class TestSearchCalendar:
    def test_params(self, connected_client):
        resp = _make_ok_response("SearchResponse", {"appt": []})
        _setup_response(connected_client, resp)

        connected_client.search_calendar(1000, 2000, folder_id="10")
        params = _get_request_params(connected_client)
        assert params["types"] == "appointment"
        assert params["calExpandInstStart"] == 1000
        assert params["calExpandInstEnd"] == 2000


class TestGetAppointment:
    def test_params(self, connected_client):
        resp = _make_ok_response("GetAppointmentResponse", {"appt": {}})
        _setup_response(connected_client, resp)

        connected_client.get_appointment("500")
        params = _get_request_params(connected_client)
        assert params["id"] == "500"


class TestCreateAppointment:
    def test_basic(self, connected_client):
        resp = _make_ok_response("CreateAppointmentResponse", {"calItemId": "700"})
        _setup_response(connected_client, resp)

        connected_client.create_appointment(
            subject="Meeting", start_time=1705312200000, end_time=1705315800000,
        )
        params = _get_request_params(connected_client)
        assert params["m"]["inv"]["comp"]["name"] == "Meeting"
        assert params["m"]["su"] == "Meeting"

    def test_with_attendees(self, connected_client):
        resp = _make_ok_response("CreateAppointmentResponse", {"calItemId": "701"})
        _setup_response(connected_client, resp)

        connected_client.create_appointment(
            subject="Meeting", start_time=1705312200000, end_time=1705315800000,
            attendees=["alice@test.com"],
        )
        params = _get_request_params(connected_client)
        assert params["m"]["inv"]["comp"]["at"][0]["a"] == "alice@test.com"


class TestGetFreeBusy:
    def test_params(self, connected_client):
        resp = _make_ok_response("GetFreeBusyResponse", {"usr": []})
        _setup_response(connected_client, resp)

        connected_client.get_free_busy("alice@test.com", 1000, 2000)
        params = _get_request_params(connected_client)
        assert params["uid"] == "alice@test.com"
        assert params["s"] == 1000
        assert params["e"] == 2000


# --- Contact methods ---


class TestSearchContacts:
    def test_params(self, connected_client):
        resp = _make_ok_response("SearchResponse", {"cn": []})
        _setup_response(connected_client, resp)

        connected_client.search_contacts("John", limit=10, offset=0)
        params = _get_request_params(connected_client)
        assert params["query"] == "John"
        assert params["types"] == "contact"


class TestGetContact:
    def test_params(self, connected_client):
        resp = _make_ok_response("GetContactsResponse", {"cn": {}})
        _setup_response(connected_client, resp)

        connected_client.get_contact("100")
        params = _get_request_params(connected_client)
        assert params["cn"]["id"] == "100"


class TestCreateContact:
    def test_params(self, connected_client):
        resp = _make_ok_response("CreateContactResponse", {"cn": {"id": "200"}})
        _setup_response(connected_client, resp)

        attrs = [{"n": "firstName", "_content": "Alice"}]
        connected_client.create_contact("7", attrs)
        params = _get_request_params(connected_client)
        assert params["cn"]["l"] == "7"
        assert params["cn"]["a"] == attrs


class TestModifyContact:
    def test_params(self, connected_client):
        resp = _make_ok_response("ModifyContactResponse", {"cn": {"id": "100"}})
        _setup_response(connected_client, resp)

        attrs = [{"n": "email", "_content": "new@test.com"}]
        connected_client.modify_contact("100", attrs)
        params = _get_request_params(connected_client)
        assert params["cn"]["id"] == "100"
        assert params["cn"]["a"] == attrs


class TestDeleteContacts:
    def test_params(self, connected_client):
        resp = _make_ok_response("ContactActionResponse", {"action": {}})
        _setup_response(connected_client, resp)

        connected_client.delete_contacts(["100", "101"])
        params = _get_request_params(connected_client)
        assert params["action"]["id"] == "100,101"
        assert params["action"]["op"] == "delete"
