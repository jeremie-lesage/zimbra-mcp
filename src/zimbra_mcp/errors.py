"""Custom exceptions for the Zimbra MCP server."""


class ZimbraMCPError(Exception):
    """Base error for the Zimbra MCP server."""

    pass


class ZimbraConnectionError(ZimbraMCPError):
    """Zimbra server connection error."""

    pass


class ZimbraAuthError(ZimbraMCPError):
    """Zimbra authentication error."""

    pass


class ZimbraNotFoundError(ZimbraMCPError):
    """Resource not found in Zimbra."""

    pass


class ZimbraOperationError(ZimbraMCPError):
    """Error during a Zimbra operation."""

    pass
