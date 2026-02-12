"""Tests for email tools."""

from unittest.mock import MagicMock, patch

import pytest

from tests.conftest import capture_tools
from zimbra_mcp.tools.emails import (
    _convert_iso_dates,
    _extract_address,
    _extract_addresses,
    _extract_parts,
    _flatten_folders,
    _guess_extension,
    _html_to_text,
    register_email_tools,
)


# --- Helper function tests ---


class TestConvertIsoDates:
    def test_after_date(self):
        assert _convert_iso_dates("after:2024-01-15") == "after:01/15/2024"

    def test_before_date(self):
        assert _convert_iso_dates("before:2024-12-31") == "before:12/31/2024"

    def test_both_dates(self):
        q = "after:2024-01-01 before:2024-06-30"
        assert _convert_iso_dates(q) == "after:01/01/2024 before:06/30/2024"

    def test_no_dates(self):
        assert _convert_iso_dates("in:inbox from:test") == "in:inbox from:test"


class TestHtmlToText:
    def test_simple_html(self):
        result = _html_to_text("<p>Hello <b>world</b></p>")
        assert "Hello" in result
        assert "world" in result

    def test_script_removed(self):
        result = _html_to_text("<p>Text</p><script>alert(1)</script>")
        assert "alert" not in result

    def test_br_to_newline(self):
        result = _html_to_text("line1<br>line2")
        assert "line1" in result
        assert "line2" in result
        assert "\n" in result


class TestExtractAddress:
    def test_with_name(self):
        addrs = [{"t": "f", "d": "John", "a": "john@test.com"}]
        assert _extract_address(addrs, "f") == "John <john@test.com>"

    def test_without_name(self):
        addrs = [{"t": "f", "a": "john@test.com"}]
        assert _extract_address(addrs, "f") == "john@test.com"

    def test_not_found(self):
        addrs = [{"t": "t", "a": "bob@test.com"}]
        assert _extract_address(addrs, "f") is None

    def test_single_dict_normalized(self):
        addr = {"t": "f", "a": "john@test.com"}
        assert _extract_address(addr, "f") == "john@test.com"


class TestExtractAddresses:
    def test_multiple(self):
        addrs = [
            {"t": "t", "a": "a@test.com"},
            {"t": "t", "d": "Bob", "a": "b@test.com"},
            {"t": "f", "a": "sender@test.com"},
        ]
        result = _extract_addresses(addrs, "t")
        assert len(result) == 2
        assert result[0] == "a@test.com"
        assert result[1] == "Bob <b@test.com>"


class TestExtractParts:
    def test_text_body(self):
        parts = [{"ct": "text/plain", "content": "Hello"}]
        body, attachments = [], []
        _extract_parts(parts, body, attachments)
        assert len(body) == 1
        assert body[0]["content"] == "Hello"

    def test_attachment(self):
        parts = [{"ct": "application/pdf", "filename": "doc.pdf", "part": "2", "s": 1024}]
        body, attachments = [], []
        _extract_parts(parts, body, attachments)
        assert len(attachments) == 1
        assert attachments[0]["filename"] == "doc.pdf"

    def test_nested(self):
        parts = [{"ct": "multipart/mixed", "mp": [{"ct": "text/plain", "content": "Nested"}]}]
        body, attachments = [], []
        _extract_parts(parts, body, attachments)
        assert len(body) == 1


class TestFlattenFolders:
    def test_simple(self):
        folder = {"id": "1", "name": "INBOX", "u": 5, "n": 100}
        result = []
        _flatten_folders(folder, result)
        assert len(result) == 1
        assert result[0]["name"] == "INBOX"

    def test_nested(self):
        folder = {
            "id": "1",
            "name": "root",
            "folder": [
                {"id": "2", "name": "Inbox"},
                {"id": "3", "name": "Sent"},
            ],
        }
        result = []
        _flatten_folders(folder, result)
        assert len(result) == 3
        assert result[1]["path"] == "root/Inbox"


class TestGuessExtension:
    def test_known(self):
        assert _guess_extension("application/pdf") == ".pdf"
        assert _guess_extension("image/png") == ".png"

    def test_unknown(self):
        assert _guess_extension("application/octet-stream") == ""

    def test_with_params(self):
        assert _guess_extension("text/plain; charset=utf-8") == ".txt"


# --- Tool tests ---


@pytest.fixture
def email_tools(connected_client):
    tools = capture_tools(register_email_tools, connected_client)
    return tools, connected_client


class TestDeleteEmailsTool:
    def test_soft_delete(self, email_tools):
        tools, client = email_tools
        client.delete_messages = MagicMock()

        result = tools["delete_emails"](["1", "2"])

        client.delete_messages.assert_called_once_with(["1", "2"], hard_delete=False)
        assert result["success"] is True
        assert result["deleted_count"] == 2
        assert result["hard_delete"] is False

    def test_hard_delete(self, email_tools):
        tools, client = email_tools
        client.delete_messages = MagicMock()

        result = tools["delete_emails"](["5"], hard_delete=True)

        client.delete_messages.assert_called_once_with(["5"], hard_delete=True)
        assert result["hard_delete"] is True


class TestSearchEmailsTool:
    def test_basic_search(self, email_tools):
        tools, client = email_tools
        client.search_messages = MagicMock(return_value={
            "m": [
                {
                    "id": "1",
                    "cid": "c1",
                    "su": "Test",
                    "e": [{"t": "f", "a": "from@test.com"}],
                    "d": "1700000000000",
                    "f": "u",
                }
            ],
            "total": 1,
            "more": False,
        })

        result = tools["search_emails"]("in:inbox")
        assert len(result["emails"]) == 1
        assert result["emails"][0]["subject"] == "Test"
        assert result["emails"][0]["is_unread"] is True


class TestMoveEmailsTool:
    def test_move(self, email_tools):
        tools, client = email_tools
        client.move_messages = MagicMock(return_value={"action": {"id": "1", "op": "move"}})

        result = tools["move_emails"](["1"], "5")
        assert result["success"] is True
        assert result["moved_count"] == 1


class TestMarkAsReadTool:
    def test_mark_read(self, email_tools):
        tools, client = email_tools
        client.mark_as_read = MagicMock()

        result = tools["mark_as_read"](["1", "2"])
        assert result["status"] == "read"

    def test_mark_unread(self, email_tools):
        tools, client = email_tools
        client.mark_as_read = MagicMock()

        result = tools["mark_as_read"](["1"], read=False)
        assert result["status"] == "unread"
