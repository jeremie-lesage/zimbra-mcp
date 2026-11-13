"""Zimbra MCP server configuration."""

import os
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

from dotenv import load_dotenv

_TRUE_VALUES = ("true", "1", "yes")


def _env_flag(name: str) -> bool:
    return os.getenv(name, "").lower() in _TRUE_VALUES


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or raw == "":
        return default
    try:
        value = int(raw)
    except ValueError:
        raise ValueError(f"{name} must be an integer, got {raw!r}")
    if value <= 0:
        raise ValueError(f"{name} must be > 0, got {value}")
    return value


@dataclass
class ZimbraConfig:
    """Configuration for Zimbra connection."""

    url: str
    user: str
    password: str = field(repr=False)
    timeout: int = 30
    enable_send: bool = False
    enable_hard_delete: bool = False
    download_dir: Path | None = None
    max_attachment_bytes: int = 50 * 1024 * 1024
    allow_insecure_http: bool = False

    def __post_init__(self) -> None:
        parts = urlsplit(self.url)
        if parts.scheme not in ("https", "http") or not parts.netloc:
            raise ValueError(f"ZIMBRA_URL must be an http(s) URL, got {self.url!r}")
        if parts.scheme == "http" and not self.allow_insecure_http:
            raise ValueError(
                "ZIMBRA_URL uses plain HTTP: credentials and auth token would be sent "
                "unencrypted. Use https:// or set ZIMBRA_ALLOW_INSECURE_HTTP=true."
            )
        if self.download_dir is not None:
            self.download_dir = Path(self.download_dir).expanduser().resolve()

    @property
    def base_url(self) -> str:
        """Server root URL (scheme://host[:port]), without the SOAP path."""
        parts = urlsplit(self.url)
        return f"{parts.scheme}://{parts.netloc}"

    @classmethod
    def from_env(cls) -> "ZimbraConfig":
        """Load configuration from environment variables."""
        load_dotenv()

        url = os.getenv("ZIMBRA_URL")
        user = os.getenv("ZIMBRA_USER")
        password = os.getenv("ZIMBRA_PASSWORD")

        if not url:
            raise ValueError("ZIMBRA_URL not defined")
        if not user:
            raise ValueError("ZIMBRA_USER not defined")
        if not password:
            raise ValueError("ZIMBRA_PASSWORD not defined")

        download_dir = os.getenv("ZIMBRA_DOWNLOAD_DIR")

        return cls(
            url=url,
            user=user,
            password=password,
            timeout=_env_int("ZIMBRA_TIMEOUT", 30),
            enable_send=_env_flag("ZIMBRA_ENABLE_SEND"),
            enable_hard_delete=_env_flag("ZIMBRA_ENABLE_HARD_DELETE"),
            download_dir=Path(download_dir) if download_dir else None,
            max_attachment_bytes=_env_int("ZIMBRA_MAX_ATTACHMENT_MB", 50) * 1024 * 1024,
            allow_insecure_http=_env_flag("ZIMBRA_ALLOW_INSECURE_HTTP"),
        )
