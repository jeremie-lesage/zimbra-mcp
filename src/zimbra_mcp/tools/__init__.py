"""MCP tools for Zimbra."""

from zimbra_mcp.tools.emails import register_email_tools
from zimbra_mcp.tools.tags import register_tag_tools
from zimbra_mcp.tools.calendar import register_calendar_tools

__all__ = ["register_email_tools", "register_tag_tools", "register_calendar_tools"]
