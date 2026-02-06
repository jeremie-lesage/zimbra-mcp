"""MCP tools for Zimbra email management."""

import os
import re
from pathlib import Path
from typing import Any

from bs4 import BeautifulSoup
from mcp.server.fastmcp import FastMCP

from zimbra_mcp.client import ZimbraClient


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

    # Extract text
    text = soup.get_text(separator=" ")

    # Clean up multiple spaces and empty lines
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n\n", text)
    text = text.strip()

    return text


def register_email_tools(mcp: FastMCP, client: ZimbraClient) -> None:
    """Register email management tools.

    Args:
        mcp: FastMCP instance
        client: Zimbra client
    """

    @mcp.tool()
    def search_emails(
        query: str,
        limit: int = 50,
        offset: int = 0,
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

        Returns:
            List of found emails with their metadata
        """
        # Convert ISO dates to Zimbra format
        query = _convert_iso_dates(query)
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
        """List all mail folders.

        Returns:
            Folder tree with their IDs and counters
        """
        result = client.get_folder("/")

        folders = []
        folder_data = result.get("folder", {})
        if isinstance(folder_data, list):
            for f in folder_data:
                _flatten_folders(f, folders)
        else:
            _flatten_folders(folder_data, folders)

        return {"folders": folders}

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
    def create_draft(
        to: list[str],
        subject: str,
        body: str,
        cc: list[str] | None = None,
        bcc: list[str] | None = None,
    ) -> dict[str, Any]:
        """Create an email draft (without sending it).

        Args:
            to: List of primary recipients
            subject: Email subject
            body: Message body (plain text)
            cc: List of CC recipients (optional)
            bcc: List of BCC recipients (optional)

        Returns:
            Information about the created draft
        """
        result = client.create_draft(to, subject, body, cc=cc, bcc=bcc)

        msg = result.get("m", {})
        if isinstance(msg, list):
            msg = msg[0] if msg else {}

        return {
            "success": True,
            "draft_id": msg.get("id"),
            "to": to,
            "cc": cc,
            "bcc": bcc,
            "subject": subject,
            "body_preview": body[:200] + "..." if len(body) > 200 else body,
        }

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
        final_filename = filename or original_filename
        if not final_filename or final_filename == "attachment":
            # Fallback: use part_id and guess extension from content_type
            ext = _guess_extension(content_type)
            final_filename = f"attachment_{msg_id}_{part_id.replace('.', '_')}{ext}"

        # Write file
        file_path = save_dir / final_filename
        file_path.write_bytes(content)

        return {
            "success": True,
            "filename": final_filename,
            "path": str(file_path),
            "size": len(content),
            "content_type": content_type,
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


def _flatten_folders(folder: dict, result: list[dict], path: str = "") -> None:
    """Flatten the folder tree."""
    folder_name = folder.get("name", "")
    folder_path = f"{path}/{folder_name}" if path else folder_name

    folder_info = {
        "id": folder.get("id"),
        "name": folder_name,
        "path": folder_path,
        "unread_count": folder.get("u", 0),
        "total_count": folder.get("n", 0),
        "view": folder.get("view", "message"),
    }
    result.append(folder_info)

    subfolders = folder.get("folder", [])
    if not isinstance(subfolders, list):
        subfolders = [subfolders]
    for subfolder in subfolders:
        _flatten_folders(subfolder, result, folder_path)
