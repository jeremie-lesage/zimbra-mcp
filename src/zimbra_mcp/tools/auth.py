"""MCP tools for Zimbra authentication (interactive two-factor login)."""

from typing import Any

from mcp.server.fastmcp import FastMCP

from zimbra_mcp.client import ZimbraClient


def register_auth_tools(mcp: FastMCP, client: ZimbraClient) -> None:
    """Register authentication tools.

    These drive interactive two-factor login: the user supplies a current TOTP
    code, the client completes the SOAP ``AuthRequest``, and the resulting
    session token is reused by every other tool until it expires (~48h).

    Args:
        mcp: FastMCP instance
        client: Zimbra client
    """

    @mcp.tool()
    def zimbra_authenticate(code: str) -> dict[str, Any]:
        """Complete Zimbra two-factor login with a current authenticator code.

        Call this when another tool reports that authentication is required.
        Ask the user for the current 6-digit code from their authenticator app
        and pass it here. The session lasts about 48 hours; re-run when it
        expires.

        Args:
            code: Current 6-digit TOTP code from the user's authenticator app.

        Returns:
            Authentication status and the account it applies to.
        """
        client.authenticate(totp_code=code.strip())
        return {
            "status": "authenticated",
            "user": client.config.user,
            "session_lifetime_hours": 48,
        }

    @mcp.tool()
    def zimbra_auth_status() -> dict[str, Any]:
        """Report whether there is an active authenticated Zimbra session.

        Returns:
            Whether a session token is held and the configured account.
        """
        return {
            "authenticated": client.is_connected,
            "user": client.config.user,
        }
