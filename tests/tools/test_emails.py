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

    def test_shared_mountpoint(self):
        folder = {
            "id": "1",
            "name": "root",
            "link": {
                "id": "300",
                "name": "Shared",
                "owner": "boss@example.com",
                "zid": "abc",
                "rid": "2",
                "folder": [{"id": "abc:400", "name": "Sub"}],
            },
        }
        result = []
        _flatten_folders(folder, result)
        assert [f["path"] for f in result] == ["root", "root/Shared", "root/Shared/Sub"]
        assert "shared" not in result[0]
        assert result[1]["shared"] is True
        assert result[2]["owner"] == "boss@example.com"
        assert result[2]["id"] == "abc:400"


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


class TestSearchEmailsInFolder:
    def _mock_tree(self):
        return {
            "folder": {
                "id": "1",
                "name": "USER_ROOT",
                "folder": [{"id": "2", "name": "Inbox"}],
                "link": {
                    "id": "300",
                    "name": "Shared",
                    "owner": "boss@example.com",
                    "zid": "abc",
                    "rid": "2",
                    "folder": [
                        {"id": "abc:400", "name": "A", "folder": {"id": "abc:401", "name": "A1"}},
                        {"id": "abc:500", "name": "B"},
                    ],
                },
            }
        }

    def test_single_folder(self, email_tools):
        tools, client = email_tools
        client.search_messages = MagicMock(return_value={"m": []})
        client.get_folder = MagicMock()

        tools["search_emails"]("from:x", folder_id="abc:400")

        client.get_folder.assert_not_called()
        query = client.search_messages.call_args[0][0]
        assert query == '(inid:"abc:400") (from:x)'

    def test_shared_subtree(self, email_tools):
        tools, client = email_tools
        client.search_messages = MagicMock(return_value={"m": []})
        client.get_folder = MagicMock(return_value=self._mock_tree())

        tools["search_emails"](folder_id="300", include_subfolders=True)

        client.get_folder.assert_called_once_with("/", traverse_mountpoints=True)
        query = client.search_messages.call_args[0][0]
        assert query == '(inid:"300" OR inid:"abc:400" OR inid:"abc:401" OR inid:"abc:500")'

    def test_subtree_by_remote_id(self, email_tools):
        tools, client = email_tools
        client.search_messages = MagicMock(return_value={"m": []})
        client.get_folder = MagicMock(return_value=self._mock_tree())

        tools["search_emails"]("subject:x", folder_id="abc:400", include_subfolders=True)

        query = client.search_messages.call_args[0][0]
        assert query == '(inid:"abc:400" OR inid:"abc:401") (subject:x)'

    def test_subtree_folder_not_found(self, email_tools):
        tools, client = email_tools
        client.search_messages = MagicMock()
        client.get_folder = MagicMock(return_value=self._mock_tree())

        result = tools["search_emails"](folder_id="999", include_subfolders=True)

        assert result["success"] is False
        client.search_messages.assert_not_called()

    def test_empty_query_without_folder_rejected(self, email_tools):
        tools, client = email_tools
        client.search_messages = MagicMock()

        result = tools["search_emails"]("  ")

        assert result["success"] is False
        client.search_messages.assert_not_called()


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
        assert result["filename"] == "attachment_99_2_1.pdf"
        assert (tmp_path / "attachment_99_2_1.pdf").read_bytes() == b"y"


# --- HTML bodies ---

from zimbra_mcp.tools.emails import _sanitize_html  # noqa: E402

HTML_ORIGINAL = {
    "m": {
        "e": [
            {"t": "f", "d": "Jonathan", "a": "jonathan@customer.test"},
            {"t": "t", "a": "test@example.com"},
        ],
        "d": "1700000000000",
        "su": "Supplier pricing",
        "mp": [{"ct": "multipart/alternative", "mp": [
            {"ct": "text/plain", "content": "Original plain"},
            {"ct": "text/html", "content": (
                "<html><head><style>p{color:red}</style></head><body>"
                "<p style=\"color:#333\">Original <b>bold</b></p>"
                "<img src=\"cid:logo123\" alt=\"Logo\">"
                "<img src=\"https://cdn.customer.test/banner.png\">"
                "<script>alert(1)</script></body></html>"
            )},
        ]}],
    }
}


class TestSanitizeHtml:
    def test_strips_script_and_handlers(self):
        out = _sanitize_html('<p onclick="x()">Hi</p><script>alert(1)</script>')
        assert "script" not in out and "alert" not in out and "onclick" not in out
        assert "<p>Hi</p>" in out

    def test_strips_javascript_links(self):
        out = _sanitize_html('<a href="javascript:alert(1)">x</a><a href="https://synaq.com">y</a>')
        assert "javascript" not in out
        assert 'href="https://synaq.com"' in out

    def test_keeps_safe_inline_style_drops_url(self):
        out = _sanitize_html('<p style="color: red; background-image: url(https://t.test/p.gif)">x</p>')
        assert "color" in out and "url(" not in out

    def test_strict_mode_drops_images(self):
        assert "<img" not in _sanitize_html('<p>a</p><img src="https://x.test/a.png">')

    def test_quoted_mode_drops_cid_keeps_https_images(self):
        out = _sanitize_html(
            '<img src="cid:logo"><img src="https://x.test/a.png">', allow_images=True,
        )
        assert "cid:" not in out
        assert 'src="https://x.test/a.png"' in out


class TestCreateDraftHtml:
    def test_html_only_derives_plain_text(self, email_tools):
        tools, client = email_tools
        client.create_draft = MagicMock(return_value={"m": {"id": "70"}})
        tools["create_draft"](to=["bob@test.com"], subject="Hi", body_html="<p>Hello <b>Bob</b></p>")
        args, kwargs = client.create_draft.call_args
        assert "Hello" in args[2] and "Bob" in args[2] and "<" not in args[2]
        assert kwargs["body_html"] == "<p>Hello <b>Bob</b></p>"

    def test_model_html_is_sanitised(self, email_tools):
        tools, client = email_tools
        client.create_draft = MagicMock(return_value={"m": {"id": "71"}})
        tools["create_draft"](to=["b@test.com"], subject="Hi", body="x",
                              body_html="<p>Hi</p><script>bad()</script>")
        assert "script" not in client.create_draft.call_args.kwargs["body_html"]

    def test_draft_id_passed_through(self, email_tools):
        tools, client = email_tools
        client.create_draft = MagicMock(return_value={"m": {"id": "72"}})
        result = tools["create_draft"](to=["b@test.com"], subject="Hi", body="v2", draft_id="72")
        assert client.create_draft.call_args.kwargs["draft_id"] == "72"
        assert result["draft_id"] == "72"

    def test_html_reply_quotes_original_html(self, email_tools):
        tools, client = email_tools
        client.get_message = MagicMock(return_value=HTML_ORIGINAL)
        client.create_draft = MagicMock(return_value={"m": {"id": "73"}})
        tools["create_draft"](to=["jonathan@customer.test"], subject="RE: Supplier pricing",
                              body_html="<p>Thanks Jonathan</p>", orig_msg_id="9", reply_type="r")
        kwargs = client.create_draft.call_args.kwargs
        html = kwargs["body_html"]
        assert html.index("Thanks Jonathan") < html.index("<blockquote")
        assert "<b>bold</b>" in html                      # original formatting kept
        assert "Jonathan &lt;jonathan@customer.test&gt;" in html  # header escaped
        assert "Supplier pricing" in html
        assert "cid:" not in html and "alert" not in html and "<style" not in html
        assert "https://cdn.customer.test/banner.png" in html
        plain = client.create_draft.call_args.args[2]
        assert "> Original plain" in plain                # plain part still quoted

    def test_html_forward_has_no_blockquote(self, email_tools):
        tools, client = email_tools
        client.get_message = MagicMock(return_value=HTML_ORIGINAL)
        client.create_draft = MagicMock(return_value={"m": {"id": "74"}})
        tools["create_draft"](to=["x@test.com"], subject="FW: Supplier pricing",
                              body_html="<p>FYI</p>", orig_msg_id="9", reply_type="w")
        html = client.create_draft.call_args.kwargs["body_html"]
        assert "Forwarded Message" in html and "<blockquote" not in html
        assert "<b>bold</b>" in html

    def test_html_reply_to_plain_original_escapes_text(self, email_tools):
        tools, client = email_tools
        client.get_message = MagicMock(return_value={"m": {
            "e": [{"t": "f", "a": "a@test.com"}], "d": "1700000000000", "su": "s",
            "mp": [{"ct": "text/plain", "content": "line1 <tag>\nline2"}],
        }})
        client.create_draft = MagicMock(return_value={"m": {"id": "75"}})
        tools["create_draft"](to=["a@test.com"], subject="RE: s",
                              body_html="<p>ok</p>", orig_msg_id="9", reply_type="r")
        html = client.create_draft.call_args.kwargs["body_html"]
        assert "line1 &lt;tag&gt;<br>" in html and "line2" in html

    def test_plain_reply_unchanged_when_no_html(self, email_tools):
        tools, client = email_tools
        client.get_message = MagicMock(return_value=HTML_ORIGINAL)
        client.create_draft = MagicMock(return_value={"m": {"id": "76"}})
        tools["create_draft"](to=["j@test.com"], subject="RE", body="Thanks",
                              orig_msg_id="9", reply_type="r")
        assert client.create_draft.call_args.kwargs["body_html"] is None


class TestHtmlToTextStructure:
    def test_list_items_on_own_lines_with_bullets(self):
        out = _html_to_text("<p>Points:</p><ul><li>first</li><li>second</li></ul>")
        assert "- first\n" in out and "- second" in out

    def test_table_rows_on_own_lines(self):
        out = _html_to_text("<table><tr><td>Plan</td><td>Seats</td></tr><tr><td>SM</td><td>250</td></tr></table>")
        lines = [l.strip() for l in out.splitlines() if l.strip()]
        assert lines == ["Plan Seats", "SM 250"]
