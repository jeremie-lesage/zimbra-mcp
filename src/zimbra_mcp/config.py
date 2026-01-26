"""Zimbra MCP server configuration."""

import os
from dataclasses import dataclass

from dotenv import load_dotenv


@dataclass
class ZimbraConfig:
    """Configuration for Zimbra connection."""

    url: str
    user: str
    password: str
    timeout: int = 30

    @classmethod
    def from_env(cls) -> "ZimbraConfig":
        """Load configuration from environment variables."""
        load_dotenv()

        url = os.getenv("ZIMBRA_URL")
        user = os.getenv("ZIMBRA_USER")
        password = os.getenv("ZIMBRA_PASSWORD")
        timeout = int(os.getenv("ZIMBRA_TIMEOUT", "30"))

        if not url:
            raise ValueError("ZIMBRA_URL not defined")
        if not user:
            raise ValueError("ZIMBRA_USER not defined")
        if not password:
            raise ValueError("ZIMBRA_PASSWORD not defined")

        return cls(url=url, user=user, password=password, timeout=timeout)
