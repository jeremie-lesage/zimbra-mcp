"""MCP tools for Zimbra email management."""

from __future__ import annotations

import html as html_lib
import os
import re
from pathlib import Path
from typing import Any

import nh3
from bs4 import BeautifulSoup
from mcp.server.fastmcp import FastMCP

from zimbra_mcp.client import ZimbraClient
from zimbra_mcp.config import ZimbraConfig


def _convert_iso_dates(query: str) -> str:
    """Convert ISO dates (YYYY-MM-DD) to Zimbra format (MM/DD/YYYY).

    Args:
        query: Search query

    Returns:
        Query with converted dates
    """
    pattern = r"(after:|before:)(\d{4})-(\d{2})-(\d{2})"
    return re.sub(pattern, r"\1\3/\4/\2", query)


def _html_to_text(html: str) -> str:
    """Convert HTML to readable plain text.

    Args:
        html: HTML content to convert

    Returns:
        Plain text extracted from HTML
    """
    soup = BeautifulSoup(html, "html.parser")

    # Remove scripts and styles
    for element in soup(["script", "style", "head", "meta", "link"]):
        element.decompose()

    # Replace <br> and <p> with line breaks
    for br in soup.find_all("br"):
        br.replace_with("\n")
    for p in soup.find_all("p"):
        p.insert_after("\n")
    for li in soup.find_all("li"):
        li.insert_before("- ")
    for block in soup.find_all(["li", "tr", "div", "h1", "h2", "h3", "h4", "ul", "ol", "table"]):
        block.insert_after("\n")

    # Extract text
    text = soup.get_text(separator=" ")

    # Clean up multiple spaces and empty lines
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r" *\n *", "\n", text)
    text = re.sub(r"\n\s*\n+", "\n\n", text)
    text = text.strip()

    return text


_HTML_TAGS = {
    "p", "div", "span", "br", "hr", "b", "strong", "i", "em", "u", "s", "small", "sub", "sup",
    "ul", "ol", "li", "a", "blockquote", "pre", "code", "h1", "h2", "h3", "h4",
    "table", "thead", "tbody", "tfoot", "tr", "td", "th", "caption", "font", "center",
}
_HTML_ATTRIBUTES = {
    "*": {"style", "align", "title"},
    "a": {"href"},
    "td": {"colspan", "rowspan", "width", "valign", "bgcolor"},
    "th": {"colspan", "rowspan", "width", "valign", "bgcolor"},
    "table": {"width", "cellpadding", "cellspacing", "border", "bgcolor"},
    "font": {"color", "face", "size"},
    "img": {"src", "alt", "width", "height"},
}
# Inline styles keep only these properties, so nothing like background-image:url(...) survives.
_STYLE_PROPERTIES = {
    "color", "background-color", "font", "font-family", "font-size", "font-weight", "font-style",
    "text-decoration", "text-align", "text-indent", "line-height", "vertical-align", "white-space",
    "margin", "margin-top", "margin-right", "margin-bottom", "margin-left",
    "padding", "padding-top", "padding-right", "padding-bottom", "padding-left",
    "border", "border-top", "border-right", "border-bottom", "border-left",
    "border-color", "border-style", "border-width", "border-collapse",
    "width", "height", "max-width", "list-style-type",
}


def _sanitize_html(html: str, allow_images: bool = False) -> str:
    """Reduce HTML to a safe formatting subset.

    Model-written HTML gets the strict set (no images). Quoted originals keep http(s)
    images; inline cid: images are dropped because the reply does not carry the parts.
    """
    tags = set(_HTML_TAGS)
    if allow_images:
        soup = BeautifulSoup(html, "html.parser")
        for img in soup.find_all("img", src=re.compile(r"^\s*cid:", re.I)):
            img.decompose()
        html = str(soup)
        tags.add("img")
    return nh3.clean(
        html,
        tags=tags,
        attributes=_HTML_ATTRIBUTES,
        url_schemes={"http", "https", "mailto"},
        filter_style_properties=_STYLE_PROPERTIES,
    )


def _format_date(ms: Any) -> str:
    """Format a Zimbra millisecond timestamp the way the quoting header shows it."""
    from datetime import datetime, timezone
    try:
        return datetime.fromtimestamp(int(ms) / 1000, tz=timezone.utc).strftime("%Y-%m-%d %H:%M")
    except (ValueError, TypeError):
        return str(ms or "")


def _prepare_html_with_original(
    client: ZimbraClient,
    body_html: str,
    orig_msg_id: str,
    reply_type: str | None,
) -> str:
    """Append the original message to an HTML body, keeping the original's formatting."""
    # ponytail: fetches the original a second time (the plain-text quote fetched it too); one
    # extra SOAP call per HTML reply. Merge the two fetches if replies ever get latency-sensitive.
    orig_msg = client.get_message(orig_msg_id).get("m", {})
    if isinstance(orig_msg, list):
        orig_msg = orig_msg[0] if orig_msg else {}

    parts: list[dict] = []
    _extract_parts(orig_msg.get("mp", []), parts, [])
    orig_html = next((p.get("content", "") for p in parts
                      if p.get("content_type", "").startswith("text/html")), "")
    if orig_html:
        soup = BeautifulSoup(orig_html, "html.parser")
        orig_html = _sanitize_html(
            soup.body.decode_contents() if soup.body else str(soup), allow_images=True,
        )
    else:
        orig_text = next((p.get("content", "") for p in parts
                          if p.get("content_type") == "text/plain"), "")
        if not orig_text:
            return body_html
        orig_html = html_lib.escape(orig_text).replace("\n", "<br>")

    esc = html_lib.escape
    addrs = orig_msg.get("e", [])
    rows = [
        ("From", esc(_extract_address(addrs, "f") or "")),
        ("To", esc(", ".join(_extract_addresses(addrs, "t")))),
        ("Cc", esc(", ".join(_extract_addresses(addrs, "c")))),
        ("Sent", esc(_format_date(orig_msg.get("d", "")))),
        ("Subject", esc(orig_msg.get("su", ""))),
    ]
    header = "".join(f"<b>{k}: </b>{v}<br>" for k, v in rows if v)
    header_style = "font-family:Helvetica,Arial,sans-serif;font-size:12pt;color:#000"

    if reply_type == "w":
        return (
            f"{body_html}<br><br>----- Forwarded Message -----<br>"
            f'<div style="{header_style}">{header}</div><br>{orig_html}'
        )
    return (
        f'{body_html}<br><hr><div style="{header_style}">{header}</div><br>'
        f'<blockquote style="border-left:2px solid #1010FF;margin-left:5px;padding-left:5px">'
        f"{orig_html}</blockquote>"
    )


def _compose(
    client: ZimbraClient,
    body: str,
    body_html: str | None,
    orig_msg_id: str | None,
    reply_type: str | None,
    include_original: str | None,
) -> tuple[str, str | None, str | None, str | None]:
    """Build the final plain and HTML bodies for a draft or send.

    Returns:
        Tuple of (full_body, full_html, attach_msg_id, include_original)
    """
    full_html = _sanitize_html(body_html) if body_html else None
    if full_html is not None and not body.strip():
        body = _html_to_text(full_html)
    full_body, attach_msg_id = body, None

    if orig_msg_id and include_original is None:
        include_original = "inline"
    if orig_msg_id and include_original and include_original != "none":
        full_body, attach_msg_id = _prepare_body_with_original(
            client, body, orig_msg_id, reply_type, include_original,
        )
        if full_html is not None and include_original == "inline":
            full_html = _prepare_html_with_original(client, full_html, orig_msg_id, reply_type)
    return full_body, full_html, attach_msg_id, include_original


def _prepare_body_with_original(
    client: ZimbraClient,
    body: str,
    orig_msg_id: str,
    reply_type: str | None,
    include_original: str | None,
) -> tuple[str, str | None]:
    """Prepare body with original message included.

    Returns:
        Tuple of (full_body, attach_msg_id)
    """
    if not include_original:
        return body, None

    if include_original == "attachment":
        return body, orig_msg_id

    if include_original != "inline":
        return body, None

    orig_result = client.get_message(orig_msg_id)
    orig_msg = orig_result.get("m", {})
    if isinstance(orig_msg, list):
        orig_msg = orig_msg[0] if orig_msg else {}

    orig_parts: list[dict] = []
    _extract_parts(orig_msg.get("mp", []), orig_parts, [])
    orig_text = ""
    for part in orig_parts:
        if part.get("content_type") == "text/plain":
            orig_text = part.get("content", "")
            break
    if not orig_text:
        for part in orig_parts:
            if part.get("content_type", "").startswith("text/html"):
                orig_text = _html_to_text(part.get("content", ""))
                break

    if not orig_text:
        return body, None

    orig_from = _extract_address(orig_msg.get("e", []), "f") or ""
    orig_date = orig_msg.get("d", "")
    if orig_date:
        from datetime import datetime, timezone
        try:
            dt = datetime.fromtimestamp(
                int(orig_date) / 1000, tz=timezone.utc,
            )
            orig_date = dt.strftime("%Y-%m-%d %H:%M")
        except (ValueError, TypeError):
            pass

    if reply_type == "w":
        orig_to = _extract_addresses(orig_msg.get("e", []), "t")
        orig_subject = orig_msg.get("su", "")
        full_body = (
            f"{body}\n\n"
            f"---------- Forwarded message ---------\n"
            f"From: {orig_from}\n"
            f"Date: {orig_date}\n"
            f"Subject: {orig_subject}\n"
            f"To: {', '.join(orig_to)}\n\n"
            f"{orig_text}"
        )
    else:
        quoted = "\n".join(
            f"> {line}" for line in orig_text.splitlines()
        )
        full_body = (
            f"{body}\n\n"
            f"On {orig_date}, {orig_from} wrote:\n"
            f"{quoted}"
        )

    return full_body, None


def register_email_tools(mcp: FastMCP, client: ZimbraClient, config: ZimbraConfig | None = None) -> None:
    """Register email management tools.

    Args:
        mcp: FastMCP instance
        client: Zimbra client
        config: Optional config (used to gate send_email)
    """

    @mcp.tool()
    def search_emails(
        query: str = "",
        limit: int = 50,
        offset: int = 0,
        folder_id: str | None = None,
        include_subfolders: bool = False,
    ) -> dict[str, Any]:
        """Search emails with Zimbra syntax.

        Args:
            query: Zimbra search query. Examples:
                - "in:inbox" : emails in inbox
                - "from:john@example.com" : emails from John
                - "tag:important" : emails with important tag
                - "subject:meeting" : emails containing meeting in subject
                - "after:2024-01-01 before:2024-12-31" : date range (ISO or MM/DD/YYYY)
                - "has:attachment" : emails with attachments
                - Combinations: "in:inbox from:boss tag:urgent"
                - Boolean operators: "from:john OR from:mary", "NOT is:read", "-tag:spam"
                - Parentheses: "(from:john OR from:mary) subject:urgent"
            limit: Maximum number of results (default: 50)
            offset: Offset for pagination
            folder_id: Restrict the search to this folder ID (use list_folders or
                search_folder to get it). Works with shared folders and their subfolders.
            include_subfolders: With folder_id, also search all its subfolders
                (e.g. a whole shared folder tree)

        Returns:
            List of found emails with their metadata
        """
        if not query.strip() and not folder_id:
            return {"success": False, "error": "Provide a query or a folder_id"}

        # Convert ISO dates to Zimbra format
        query = _convert_iso_dates(query)

        if folder_id:
            folder_ids = [folder_id]
            if include_subfolders:
                tree = client.get_folder("/", traverse_mountpoints=True)
                for root in _root_folders(tree):
                    found = _find_folder(root, folder_id)
                    if found is not None:
                        folder_ids = []
                        _collect_folder_ids(found, folder_ids)
                        break
                else:
                    return {"success": False, "error": f"Folder not found: {folder_id}"}
            folder_clause = " OR ".join(f'inid:"{fid}"' for fid in folder_ids)
            folder_clause = f"({folder_clause})"
            query = f"{folder_clause} ({query})" if query.strip() else folder_clause
        result = client.search_messages(query, limit=limit, offset=offset)

        messages = result.get("m", [])
        if not isinstance(messages, list):
            messages = [messages]

        emails = []
        for msg in messages:
            email_info = {
                "id": msg.get("id"),
                "conversation_id": msg.get("cid"),
                "subject": msg.get("su", "(no subject)"),
                "from": _extract_address(msg.get("e", []), "f"),
                "to": _extract_addresses(msg.get("e", []), "t"),
                "date": msg.get("d"),
                "size": msg.get("s"),
                "folder": msg.get("l"),
                "flags": msg.get("f", ""),
                "tags": msg.get("t", "").split(",") if msg.get("t") else [],
                "has_attachment": "a" in msg.get("f", ""),
                "is_unread": "u" in msg.get("f", ""),
                "is_flagged": "f" in msg.get("f", ""),
                "fragment": msg.get("fr", ""),
            }
            emails.append(email_info)

        return {
            "emails": emails,
            "total": result.get("total", len(emails)),
            "more": result.get("more", False),
            "offset": offset,
        }

    @mcp.tool()
    def get_email(
        msg_id: str,
        include_raw: bool = False,
        strip_html: bool = True,
    ) -> dict[str, Any]:
        """Retrieve a complete email by its ID.

        Args:
            msg_id: Email ID (obtained via search_emails)
            include_raw: Include raw MIME message
            strip_html: Convert HTML to plain text (default: True).
                Significantly reduces the size of HTML newsletters.

        Returns:
            Complete email with body, headers, and attachments
        """
        result = client.get_message(msg_id, raw=include_raw)

        msg = result.get("m", {})
        if isinstance(msg, list):
            msg = msg[0] if msg else {}

        body_parts = []
        attachments = []
        _extract_parts(msg.get("mp", []), body_parts, attachments)

        # Convert HTML to text if requested
        if strip_html:
            for part in body_parts:
                if part.get("content_type") == "text/html":
                    part["content"] = _html_to_text(part["content"])
                    part["content_type"] = "text/plain (converted from HTML)"

        email_detail = {
            "id": msg.get("id"),
            "conversation_id": msg.get("cid"),
            "subject": msg.get("su", "(no subject)"),
            "from": _extract_address(msg.get("e", []), "f"),
            "to": _extract_addresses(msg.get("e", []), "t"),
            "cc": _extract_addresses(msg.get("e", []), "c"),
            "bcc": _extract_addresses(msg.get("e", []), "b"),
            "reply_to": _extract_address(msg.get("e", []), "r"),
            "date": msg.get("d"),
            "size": msg.get("s"),
            "folder": msg.get("l"),
            "flags": msg.get("f", ""),
            "tags": msg.get("t", "").split(",") if msg.get("t") else [],
            "body": body_parts,
            "attachments": attachments,
        }

        if include_raw and msg.get("content"):
            email_detail["raw"] = msg.get("content")

        return email_detail

    @mcp.tool()
    def list_folders() -> dict[str, Any]:
        """List all mail folders, including shared folders and their subfolders.

        Shared folders (and their subfolders) are flagged with "shared": true
        and the "owner" of the share.

        Returns:
            Folder tree with their IDs and counters
        """
        result = client.get_folder("/", traverse_mountpoints=True)

        folders: list[dict] = []
        for f in _root_folders(result):
            _flatten_folders(f, folders)

        return {"folders": folders}

    @mcp.tool()
    def search_folder(name: str) -> dict[str, Any]:
        """Search for a folder by name or path.

        Performs case-insensitive partial matching on both folder name and path.
        Use this instead of list_folders when you know the folder name you're looking for.

        Args:
            name: Search term to match against folder name or path

        Returns:
            Matching folders with their IDs, paths, and counters
        """
        result = client.get_folder("/", traverse_mountpoints=True)

        all_folders: list[dict] = []
        for f in _root_folders(result):
            _flatten_folders(f, all_folders)

        query_lower = name.lower()
        matches = [
            f for f in all_folders
            if query_lower in f["name"].lower() or query_lower in f["path"].lower()
        ]

        return {
            "folders": matches,
            "query": name,
            "total": len(matches),
        }

    @mcp.tool()
    def move_emails(msg_ids: list[str], folder_id: str) -> dict[str, Any]:
        """Move emails to a folder.

        Args:
            msg_ids: List of email IDs to move
            folder_id: Destination folder ID (use list_folders to get them)

        Returns:
            Move confirmation
        """
        result = client.move_messages(msg_ids, folder_id)

        return {
            "success": True,
            "moved_count": len(msg_ids),
            "destination_folder": folder_id,
            "action": result.get("action", {}),
        }

    @mcp.tool()
    def mark_as_read(msg_ids: list[str], read: bool = True) -> dict[str, Any]:
        """Mark emails as read or unread.

        Args:
            msg_ids: List of email IDs
            read: True to mark as read (default), False for unread

        Returns:
            Operation confirmation
        """
        client.mark_as_read(msg_ids, read=read)
        return {
            "success": True,
            "marked_count": len(msg_ids),
            "status": "read" if read else "unread",
        }

    @mcp.tool()
    def delete_emails(msg_ids: list[str], hard_delete: bool = False) -> dict[str, Any]:
        """Delete emails.

        By default, emails are moved to Trash (soft delete).
        IMPORTANT: Only set hard_delete=True if the user explicitly asks for
        permanent deletion. Never use hard_delete on your own initiative.

        Args:
            msg_ids: List of email IDs to delete
            hard_delete: If True, permanently delete (ONLY when explicitly requested by user); otherwise move to Trash (default: False)

        Returns:
            Deletion confirmation
        """
        client.delete_messages(msg_ids, hard_delete=hard_delete)
        return {
            "success": True,
            "deleted_count": len(msg_ids),
            "hard_delete": hard_delete,
        }

    @mcp.tool()
    def create_draft(
        to: list[str],
        subject: str,
        body: str = "",
        cc: list[str] | None = None,
        bcc: list[str] | None = None,
        orig_msg_id: str | None = None,
        reply_type: str | None = None,
        include_original: str | None = None,
        body_html: str | None = None,
        draft_id: str | None = None,
    ) -> dict[str, Any]:
        """Create an email draft (without sending it), or update an existing draft.

        Use orig_msg_id + reply_type to create a reply or forward draft linked
        to the original message. This sets the conversation thread and flags
        the original message as replied/forwarded in Zimbra.

        When orig_msg_id is set, include_original defaults to "inline" (quotes
        the original message in the body). Use "attachment" to attach it as .eml
        instead, or "none" to explicitly exclude it.

        For formatted mail, pass body_html (paragraphs, bold, lists, links, tables,
        inline styles). The message then carries both HTML and plain text; if body
        is empty, the plain text is generated from body_html. Replies quote the
        original's HTML so the thread keeps its formatting. Scripts, images and
        external resources in body_html are removed.

        Args:
            to: List of primary recipients
            subject: Email subject
            body: Message body as plain text (optional when body_html is given)
            cc: List of CC recipients (optional)
            bcc: List of BCC recipients (optional)
            orig_msg_id: ID of the original message when replying or forwarding (optional)
            reply_type: "r" for reply, "w" for forward. Required when orig_msg_id is set (optional)
            include_original: How to include the original message: "inline" (default when replying/forwarding), "attachment", or "none" (optional)
            body_html: Message body as HTML (optional)
            draft_id: ID of an existing draft to replace with this content (optional)

        Returns:
            Information about the created draft
        """
        full_body, full_html, attach_msg_id, include_original = _compose(
            client, body, body_html, orig_msg_id, reply_type, include_original,
        )

        result = client.create_draft(
            to, subject, full_body, cc=cc, bcc=bcc,
            orig_msg_id=orig_msg_id, reply_type=reply_type,
            attach_msg_id=attach_msg_id, body_html=full_html, draft_id=draft_id,
        )

        msg = result.get("m", {})
        if isinstance(msg, list):
            msg = msg[0] if msg else {}

        response = {
            "success": True,
            "draft_id": msg.get("id"),
            "format": "html" if full_html else "text",
            "to": to,
            "cc": cc,
            "bcc": bcc,
            "subject": subject,
            "body_preview": full_body[:200] + "..." if len(full_body) > 200 else full_body,
        }
        if orig_msg_id:
            response["orig_msg_id"] = orig_msg_id
            response["reply_type"] = reply_type
            response["include_original"] = include_original
        return response

    @mcp.tool()
    def download_attachment(
        msg_id: str,
        part_id: str,
        save_path: str,
        filename: str | None = None,
    ) -> dict[str, Any]:
        """Download an email attachment and save it to a file.

        Args:
            msg_id: Email ID (obtained via search_emails or get_email)
            part_id: Attachment part ID (obtained from get_email attachments list)
            save_path: Directory where to save the file (must exist)
            filename: Optional custom filename (if not provided, uses original filename)

        Returns:
            Information about the downloaded file (path, size, content_type)
        """
        # Validate save_path
        save_dir = Path(save_path).expanduser().resolve()
        if not save_dir.exists():
            return {
                "success": False,
                "error": f"Directory does not exist: {save_path}",
            }
        if not save_dir.is_dir():
            return {
                "success": False,
                "error": f"Path is not a directory: {save_path}",
            }

        # Download attachment content
        content, original_filename, content_type = client.get_attachment_content(msg_id, part_id)

        # Determine final filename
        final_filename = Path(filename or original_filename or "").name
        if not final_filename or final_filename in (".", "..") or final_filename == "attachment":
            # Fallback: use part_id and guess extension from content_type
            ext = _guess_extension(content_type)
            final_filename = f"attachment_{msg_id}_{part_id.replace('.', '_')}{ext}"

        # Write file
        file_path = (save_dir / final_filename).resolve()
        if save_dir != file_path.parent:
            return {
                "success": False,
                "error": "Invalid filename: resolved outside the target directory",
            }
        file_path.write_bytes(content)

        return {
            "success": True,
            "filename": final_filename,
            "path": str(file_path),
            "size": len(content),
            "content_type": content_type,
        }

    # Conditionally register send_email tool
    if config and config.enable_send:
        @mcp.tool()
        def send_email(
            to: list[str],
            subject: str,
            body: str,
            cc: list[str] | None = None,
            bcc: list[str] | None = None,
            orig_msg_id: str | None = None,
            reply_type: str | None = None,
            include_original: str | None = None,
            draft_id: str | None = None,
            body_html: str | None = None,
        ) -> dict[str, Any]:
            """Send an email directly. WARNING: sends immediately, cannot be undone.

            Use orig_msg_id + reply_type to send a reply or forward linked
            to the original message. When orig_msg_id is set, include_original
            defaults to "inline" (quotes the original message in the body).
            Use "attachment" to attach it as .eml instead, or "none" to
            explicitly exclude it.

            Args:
                to: List of primary recipients
                subject: Email subject
                body: Message body (plain text)
                cc: List of CC recipients (optional)
                bcc: List of BCC recipients (optional)
                orig_msg_id: ID of the original message when replying or forwarding (optional)
                reply_type: "r" for reply, "w" for forward. Required when orig_msg_id is set (optional)
                include_original: How to include the original message: "inline" (default when replying/forwarding), "attachment", or "none" (optional)
                draft_id: ID of an existing draft to send (optional)
                body_html: Message body as HTML, sent alongside plain text (optional)

            Returns:
                Information about the sent email
            """
            full_body, full_html, attach_msg_id, include_original = _compose(
                client, body, body_html, orig_msg_id, reply_type, include_original,
            )

            result = client.send_message(
                to, subject, full_body, cc=cc, bcc=bcc,
                orig_msg_id=orig_msg_id, reply_type=reply_type,
                attach_msg_id=attach_msg_id, draft_id=draft_id, body_html=full_html,
            )

            msg = result.get("m", {})
            if isinstance(msg, list):
                msg = msg[0] if msg else {}

            return {
                "success": True,
                "message_id": msg.get("id"),
                "to": to,
                "cc": cc,
                "bcc": bcc,
                "subject": subject,
                "body_preview": full_body[:200] + "..." if len(full_body) > 200 else full_body,
            }


def _guess_extension(content_type: str) -> str:
    """Guess file extension from content type."""
    extensions = {
        "application/pdf": ".pdf",
        "image/png": ".png",
        "image/jpeg": ".jpg",
        "image/gif": ".gif",
        "text/plain": ".txt",
        "text/html": ".html",
        "application/zip": ".zip",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ".xlsx",
        "application/msword": ".doc",
        "application/vnd.ms-excel": ".xls",
    }
    return extensions.get(content_type.split(";")[0].strip(), "")


def _extract_address(addresses: list[dict], addr_type: str) -> str | None:
    """Extract an address of a given type."""
    if not isinstance(addresses, list):
        addresses = [addresses]
    for addr in addresses:
        if addr.get("t") == addr_type:
            name = addr.get("d", "")
            email = addr.get("a", "")
            if name:
                return f"{name} <{email}>"
            return email
    return None


def _extract_addresses(addresses: list[dict], addr_type: str) -> list[str]:
    """Extract all addresses of a given type."""
    if not isinstance(addresses, list):
        addresses = [addresses]
    result = []
    for addr in addresses:
        if addr.get("t") == addr_type:
            name = addr.get("d", "")
            email = addr.get("a", "")
            if name:
                result.append(f"{name} <{email}>")
            else:
                result.append(email)
    return result


def _extract_parts(
    parts: list[dict] | dict,
    body_parts: list[dict],
    attachments: list[dict],
) -> None:
    """Recursively extract message parts."""
    if not parts:
        return

    if not isinstance(parts, list):
        parts = [parts]

    for part in parts:
        content_type = part.get("ct", "")
        content = part.get("content", "")
        filename = part.get("filename", "")

        if filename or part.get("cd") == "attachment":
            attachments.append({
                "part_id": part.get("part"),
                "filename": filename or "unnamed",
                "content_type": content_type,
                "size": part.get("s"),
            })
        elif content_type.startswith("text/"):
            body_parts.append({
                "content_type": content_type,
                "content": content,
            })

        if "mp" in part:
            _extract_parts(part["mp"], body_parts, attachments)


def _subfolders(folder: dict) -> list[dict]:
    """Return the child folders and mountpoints (shared folders) of a folder."""
    children = []
    for key in ("folder", "link"):
        items = folder.get(key, [])
        if not isinstance(items, list):
            items = [items]
        children.extend(items)
    return children


def _root_folders(result: dict) -> list[dict]:
    """Return the top-level folders of a GetFolderResponse."""
    folder_data = result.get("folder", {})
    return folder_data if isinstance(folder_data, list) else [folder_data]


def _flatten_folders(
    folder: dict,
    result: list[dict],
    path: str = "",
    shared_owner: str | None = None,
) -> None:
    """Flatten the folder tree, including shared folders (mountpoints)."""
    folder_name = folder.get("name", "")
    folder_path = f"{path}/{folder_name}" if path else folder_name

    if "owner" in folder or "zid" in folder:
        shared_owner = folder.get("owner") or shared_owner or ""

    folder_info = {
        "id": folder.get("id"),
        "name": folder_name,
        "path": folder_path,
        "unread_count": folder.get("u", 0),
        "total_count": folder.get("n", 0),
        "view": folder.get("view", "message"),
    }
    if shared_owner is not None:
        folder_info["shared"] = True
        folder_info["owner"] = shared_owner
    result.append(folder_info)

    for subfolder in _subfolders(folder):
        _flatten_folders(subfolder, result, folder_path, shared_owner)


def _find_folder(folder: dict, folder_id: str) -> dict | None:
    """Find a folder or mountpoint by ID in the folder tree.

    A mountpoint also matches its remote ID ("<owner zimbraId>:<remote folder id>").
    """
    ids = {str(folder.get("id"))}
    if folder.get("zid") and folder.get("rid"):
        ids.add(f"{folder['zid']}:{folder['rid']}")
    if folder_id in ids:
        return folder
    for subfolder in _subfolders(folder):
        found = _find_folder(subfolder, folder_id)
        if found is not None:
            return found
    return None


def _collect_folder_ids(folder: dict, result: list[str]) -> None:
    """Collect the IDs of a folder and all its descendants."""
    if folder.get("id"):
        result.append(str(folder["id"]))
    for subfolder in _subfolders(folder):
        _collect_folder_ids(subfolder, result)
