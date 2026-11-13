"""MCP Server for Zimbra."""

import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator

from mcp.server.fastmcp import FastMCP

from zimbra_mcp.client import ZimbraClient
from zimbra_mcp.config import ZimbraConfig
from zimbra_mcp.errors import ZimbraAuthError, ZimbraTwoFactorRequiredError
from zimbra_mcp.tools import (
    register_auth_tools,
    register_calendar_tools,
    register_contact_tools,
    register_email_tools,
    register_tag_tools,
)

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__package__)


@asynccontextmanager
async def lifespan(mcp: FastMCP) -> AsyncIterator[dict]:
    """Manage the MCP server lifecycle.

    Initializes the Zimbra connection at startup and closes it properly at shutdown.
    """
    logger.info("Starting Zimbra MCP server...")

    try:
        config = ZimbraConfig.from_env()
        client = ZimbraClient(config)

        # Register tools before authenticating: the connection is established
        # lazily, and 2FA accounts must authenticate via the zimbra_authenticate
        # tool after startup (there is no terminal to prompt for a code here).
        register_email_tools(mcp, client, config)
        register_tag_tools(mcp, client)
        register_calendar_tools(mcp, client)
        register_contact_tools(mcp, client)
        register_auth_tools(mcp, client)
        logger.info("Tools registered: emails, tags, calendar, contacts, auth")

        try:
            client.connect()
            logger.info(f"Connected to Zimbra: {config.url} as {config.user}")
        except ZimbraTwoFactorRequiredError:
            logger.info("Two-factor auth required; awaiting code via the zimbra_authenticate tool")
        except ZimbraAuthError as e:
            logger.warning(f"Initial authentication failed ({e}); use the zimbra_authenticate tool")

        yield {"client": client}

    except Exception as e:
        logger.error(f"Error during initialization: {e}")
        raise
    finally:
        if "client" in locals():
            client.disconnect()
            logger.info("Disconnected from Zimbra")


mcp = FastMCP(
    "zimbra-mcp",
    instructions="MCP Server for Zimbra - Email, tag, calendar, and contact management",
    lifespan=lifespan,
)


def main() -> None:
    """Main entry point."""
    mcp.run()


if __name__ == "__main__":
    main()
