"""MCP tools for Zimbra tag management."""

from typing import Any

from mcp.server.fastmcp import FastMCP

from zimbra_mcp.client import ZimbraClient

# Predefined Zimbra colors (0-127)
ZIMBRA_COLORS = {
    "blue": 1,
    "cyan": 2,
    "green": 3,
    "purple": 4,
    "red": 5,
    "yellow": 6,
    "pink": 7,
    "gray": 8,
    "orange": 9,
}


def register_tag_tools(mcp: FastMCP, client: ZimbraClient) -> None:
    """Register tag management tools.

    Args:
        mcp: FastMCP instance
        client: Zimbra client
    """

    @mcp.tool()
    def list_tags() -> dict[str, Any]:
        """List all available tags.

        Returns:
            List of tags with their IDs, names, and colors
        """
        result = client.get_all_tags()

        tags = result.get("tag", [])
        if not isinstance(tags, list):
            tags = [tags] if tags else []

        tag_list = []
        for tag in tags:
            tag_info = {
                "id": tag.get("id"),
                "name": tag.get("name"),
                "color": tag.get("color"),
                "color_name": _color_id_to_name(tag.get("color")),
                "unread_count": tag.get("u", 0),
                "total_count": tag.get("n", 0),
            }
            tag_list.append(tag_info)

        return {
            "tags": tag_list,
            "available_colors": list(ZIMBRA_COLORS.keys()),
        }

    @mcp.tool()
    def create_tag(name: str, color: str | None = None) -> dict[str, Any]:
        """Create a new tag.

        Args:
            name: Tag name
            color: Tag color (optional). Possible values:
                blue, cyan, green, purple, red, yellow, pink, gray, orange

        Returns:
            Information about the created tag
        """
        color_id = None
        if color:
            color_lower = color.lower()
            if color_lower in ZIMBRA_COLORS:
                color_id = ZIMBRA_COLORS[color_lower]
            else:
                return {
                    "success": False,
                    "error": f"Invalid color: {color}. Available colors: {list(ZIMBRA_COLORS.keys())}",
                }

        result = client.create_tag(name, color=color_id)

        tag = result.get("tag", {})
        if isinstance(tag, list):
            tag = tag[0] if tag else {}

        return {
            "success": True,
            "tag": {
                "id": tag.get("id"),
                "name": tag.get("name"),
                "color": tag.get("color"),
                "color_name": color,
            },
        }

    @mcp.tool()
    def delete_tag(tag_id: str) -> dict[str, Any]:
        """Delete a tag.

        Args:
            tag_id: ID of the tag to delete (use list_tags to get the ID)

        Returns:
            Deletion confirmation
        """
        client.delete_tag(tag_id)

        return {
            "success": True,
            "deleted_tag_id": tag_id,
        }

    @mcp.tool()
    def add_tag_to_emails(msg_ids: list[str], tag_name: str) -> dict[str, Any]:
        """Add a tag to emails.

        Args:
            msg_ids: List of email IDs
            tag_name: Name of the tag to add

        Returns:
            Operation confirmation
        """
        result = client.tag_messages(msg_ids, tag_name, untag=False)

        return {
            "success": True,
            "tagged_count": len(msg_ids),
            "tag_name": tag_name,
            "action": result.get("action", {}),
        }

    @mcp.tool()
    def remove_tag_from_emails(msg_ids: list[str], tag_name: str) -> dict[str, Any]:
        """Remove a tag from emails.

        Args:
            msg_ids: List of email IDs
            tag_name: Name of the tag to remove

        Returns:
            Operation confirmation
        """
        result = client.tag_messages(msg_ids, tag_name, untag=True)

        return {
            "success": True,
            "untagged_count": len(msg_ids),
            "tag_name": tag_name,
            "action": result.get("action", {}),
        }


def _color_id_to_name(color_id: int | None) -> str | None:
    """Convert a Zimbra color ID to name."""
    if color_id is None:
        return None
    for name, cid in ZIMBRA_COLORS.items():
        if cid == color_id:
            return name
    return f"custom_{color_id}"
