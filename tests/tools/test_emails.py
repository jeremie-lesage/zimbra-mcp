"""Tests for email tools."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from tests.conftest import capture_tools
from zimbra_mcp.config import ZimbraConfig
from zimbra_mcp.tools.emails import (
    _convert_iso_dates,
    _extract_address,
    _extract_addresses,
    _extract_parts,
    _flatten_folders,
    _guess_extension,
    _html_to_text,
    _prepare_body_with_original,
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


class TestSearchFolderTool:
    def _mock_folder_tree(self):
        return {
            "folder": {
                "id": "1",
                "name": "USER_ROOT",
                "folder": [
                    {"id": "2", "name": "Inbox", "u": 3, "n": 50},
                    {"id": "3", "name": "Sent"},
                    {"id": "4", "name": "Drafts"},
                    {
                        "id": "5",
                        "name": "Work",
                        "folder": [
                            {"id": "6", "name": "Projects"},
                            {"id": "7", "name": "Inbox-Archive"},
                        ],
                    },
                ],
            }
        }

    def test_search_by_name(self, email_tools):
        tools, client = email_tools
        client.get_folder = MagicMock(return_value=self._mock_folder_tree())

        result = tools["search_folder"]("inbox")
        names = [f["name"] for f in result["folders"]]
        assert "Inbox" in names
        assert "Inbox-Archive" in names
        assert result["total"] == 2

    def test_search_case_insensitive(self, email_tools):
        tools, client = email_tools
        client.get_folder = MagicMock(return_value=self._mock_folder_tree())

        result = tools["search_folder"]("DRAFTS")
        assert result["total"] == 1
        assert result["folders"][0]["name"] == "Drafts"

    def test_search_by_path(self, email_tools):
        tools, client = email_tools
        client.get_folder = MagicMock(return_value=self._mock_folder_tree())

        result = tools["search_folder"]("Work/Projects")
        assert result["total"] >= 1
        paths = [f["path"] for f in result["folders"]]
        assert any("Work/Projects" in p for p in paths)

    def test_search_no_match(self, email_tools):
        tools, client = email_tools
        client.get_folder = MagicMock(return_value=self._mock_folder_tree())

        result = tools["search_folder"]("nonexistent")
        assert result["total"] == 0
        assert result["folders"] == []

    def test_query_preserved(self, email_tools):
        tools, client = email_tools
        client.get_folder = MagicMock(return_value=self._mock_folder_tree())

        result = tools["search_folder"]("test")
        assert result["query"] == "test"


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


class TestPrepareBodyWithOriginal:
    def test_no_include(self, connected_client):
        body, attach = _prepare_body_with_original(
            connected_client, "Hello", "123", "r", None,
        )
        assert body == "Hello"
        assert attach is None

    def test_attachment_mode(self, connected_client):
        body, attach = _prepare_body_with_original(
            connected_client, "See attached", "123", "w", "attachment",
        )
        assert body == "See attached"
        assert attach == "123"

    def test_inline_reply(self, connected_client):
        connected_client.get_message = MagicMock(return_value={
            "m": {
                "e": [{"t": "f", "a": "sender@test.com"}],
                "d": "1700000000000",
                "mp": [{"ct": "text/plain", "content": "Original text"}],
            }
        })

        body, attach = _prepare_body_with_original(
            connected_client, "My reply", "123", "r", "inline",
        )
        assert "My reply" in body
        assert "> Original text" in body
        assert attach is None

    def test_inline_forward(self, connected_client):
        connected_client.get_message = MagicMock(return_value={
            "m": {
                "e": [
                    {"t": "f", "a": "sender@test.com"},
                    {"t": "t", "a": "recipient@test.com"},
                ],
                "d": "1700000000000",
                "su": "Original Subject",
                "mp": [{"ct": "text/plain", "content": "Original text"}],
            }
        })

        body, attach = _prepare_body_with_original(
            connected_client, "FYI", "123", "w", "inline",
        )
        assert "FYI" in body
        assert "Forwarded message" in body
        assert "Original text" in body
        assert attach is None


class TestSendEmailToolRegistration:
    def test_send_email_not_registered_by_default(self, connected_client):
        tools = capture_tools(register_email_tools, connected_client)
        assert "send_email" not in tools

    def test_send_email_not_registered_when_disabled(self, connected_client):
        cfg = ZimbraConfig(url="https://z.test", user="u", password="p", enable_send=False)
        tools = capture_tools(register_email_tools, connected_client, cfg)
        assert "send_email" not in tools

    def test_send_email_registered_when_enabled(self, connected_client):
        cfg = ZimbraConfig(url="https://z.test", user="u", password="p", enable_send=True)
        tools = capture_tools(register_email_tools, connected_client, cfg)
        assert "send_email" in tools

    def test_send_email_calls_client(self, connected_client):
        cfg = ZimbraConfig(url="https://z.test", user="u", password="p", enable_send=True)
        tools = capture_tools(register_email_tools, connected_client, cfg)
        connected_client.send_message = MagicMock(return_value={"m": {"id": "200"}})

        result = tools["send_email"](
            to=["bob@test.com"], subject="Test", body="Hello",
        )

        connected_client.send_message.assert_called_once()
        assert result["success"] is True
        assert result["message_id"] == "200"


class TestDownloadAttachmentTool:
    def test_normal_filename_written_inside_dir(self, email_tools, tmp_path):
        tools, client = email_tools
        client.get_attachment_content = MagicMock(
            return_value=(b"data", "report.pdf", "application/pdf")
        )

        result = tools["download_attachment"]("1", "2", str(tmp_path))

        assert result["success"] is True
        assert result["filename"] == "report.pdf"
        assert (tmp_path / "report.pdf").read_bytes() == b"data"

    def test_traversal_in_server_filename_is_stripped_to_basename(self, email_tools, tmp_path):
        """A malicious Content-Disposition filename must not escape save_dir."""
        tools, client = email_tools
        client.get_attachment_content = MagicMock(
            return_value=(b"evil", "../../../../tmp/evil.txt", "text/plain")
        )

        result = tools["download_attachment"]("1", "2", str(tmp_path))

        assert result["success"] is True
        assert result["filename"] == "evil.txt"
        # File landed inside save_dir, and nothing was written to the parent.
        assert (tmp_path / "evil.txt").read_bytes() == b"evil"
        assert not (tmp_path.parent / "evil.txt").exists()

    def test_absolute_user_filename_is_stripped(self, email_tools, tmp_path):
        tools, client = email_tools
        client.get_attachment_content = MagicMock(
            return_value=(b"x", "orig.bin", "application/octet-stream")
        )

        result = tools["download_attachment"](
            "1", "2", str(tmp_path), filename="/etc/cron.d/pwn"
        )

        assert result["success"] is True
        assert result["filename"] == "pwn"
        assert (tmp_path / "pwn").read_bytes() == b"x"
        assert not Path("/etc/cron.d/pwn").exists()

    def test_dotdot_only_filename_falls_back(self, email_tools, tmp_path):
        tools, client = email_tools
        client.get_attachment_content = MagicMock(
            return_value=(b"y", "..", "application/pdf")
        )

        result = tools["download_attachment"]("99", "2.1", str(tmp_path))

        assert result["success"] is True
        # Reduced to "" by basename → fallback name, written inside save_dir.
        assert result["filename"] == "attachment_99_2_1.pdf"
        assert (tmp_path / "attachment_99_2_1.pdf").read_bytes() == b"y"
