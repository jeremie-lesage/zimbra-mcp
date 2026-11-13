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


class ZimbraTwoFactorRequiredError(ZimbraAuthError):
    """The account has 2FA enabled and a current TOTP code is required.

    Raised when the password is accepted but the server returns a 2FA-pending
    token (``twoFactorAuthRequired``) instead of a usable session. The caller
    should obtain a current code from the user and re-authenticate with it.
    """

    pass


class ZimbraNotFoundError(ZimbraMCPError):
    """Resource not found in Zimbra."""

    pass


class ZimbraOperationError(ZimbraMCPError):
    """Error during a Zimbra operation."""

    pass
