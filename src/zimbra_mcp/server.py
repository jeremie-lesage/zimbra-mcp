"""MCP Server for Zimbra."""

import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator

from mcp.server.fastmcp import FastMCP

from zimbra_mcp.client import ZimbraClient
from zimbra_mcp.config import ZimbraConfig
from zimbra_mcp.tools import (
    register_calendar_tools,
    register_email_tools,
    register_tag_tools,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(mcp: FastMCP) -> AsyncIterator[dict]:
    """Manage the MCP server lifecycle.

    Initializes the Zimbra connection at startup and closes it properly at shutdown.
    """
    logger.info("Starting Zimbra MCP server...")

    try:
        config = ZimbraConfig.from_env()
        client = ZimbraClient(config)
        client.connect()
        logger.info(f"Connected to Zimbra: {config.url} as {config.user}")

        register_email_tools(mcp, client)
        register_tag_tools(mcp, client)
        register_calendar_tools(mcp, client)
        logger.info("Tools registered: emails, tags, calendar")

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
    instructions="MCP Server for Zimbra - Email, tag, and calendar management",
    lifespan=lifespan,
)


def main() -> None:
    """Main entry point."""
    mcp.run()


if __name__ == "__main__":
    main()
