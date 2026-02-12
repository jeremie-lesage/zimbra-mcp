"""Tests for ZimbraConfig."""

from unittest.mock import patch

import pytest

from zimbra_mcp.config import ZimbraConfig


class TestZimbraConfig:
    @patch("zimbra_mcp.config.load_dotenv")
    def test_from_env_success(self, _mock_dotenv, monkeypatch):
        monkeypatch.setenv("ZIMBRA_URL", "https://z.test/service/soap")
        monkeypatch.setenv("ZIMBRA_USER", "u@test.com")
        monkeypatch.setenv("ZIMBRA_PASSWORD", "pw")
        monkeypatch.setenv("ZIMBRA_TIMEOUT", "60")

        cfg = ZimbraConfig.from_env()

        assert cfg.url == "https://z.test/service/soap"
        assert cfg.user == "u@test.com"
        assert cfg.password == "pw"
        assert cfg.timeout == 60

    @patch("zimbra_mcp.config.load_dotenv")
    def test_from_env_default_timeout(self, _mock_dotenv, monkeypatch):
        monkeypatch.setenv("ZIMBRA_URL", "https://z.test/service/soap")
        monkeypatch.setenv("ZIMBRA_USER", "u@test.com")
        monkeypatch.setenv("ZIMBRA_PASSWORD", "pw")
        monkeypatch.delenv("ZIMBRA_TIMEOUT", raising=False)

        cfg = ZimbraConfig.from_env()
        assert cfg.timeout == 30

    @patch("zimbra_mcp.config.load_dotenv")
    def test_from_env_missing_url(self, _mock_dotenv, monkeypatch):
        monkeypatch.delenv("ZIMBRA_URL", raising=False)
        monkeypatch.setenv("ZIMBRA_USER", "u@test.com")
        monkeypatch.setenv("ZIMBRA_PASSWORD", "pw")

        with pytest.raises(ValueError, match="ZIMBRA_URL"):
            ZimbraConfig.from_env()

    @patch("zimbra_mcp.config.load_dotenv")
    def test_from_env_missing_user(self, _mock_dotenv, monkeypatch):
        monkeypatch.setenv("ZIMBRA_URL", "https://z.test/service/soap")
        monkeypatch.delenv("ZIMBRA_USER", raising=False)
        monkeypatch.setenv("ZIMBRA_PASSWORD", "pw")

        with pytest.raises(ValueError, match="ZIMBRA_USER"):
            ZimbraConfig.from_env()

    @patch("zimbra_mcp.config.load_dotenv")
    def test_from_env_missing_password(self, _mock_dotenv, monkeypatch):
        monkeypatch.setenv("ZIMBRA_URL", "https://z.test/service/soap")
        monkeypatch.setenv("ZIMBRA_USER", "u@test.com")
        monkeypatch.delenv("ZIMBRA_PASSWORD", raising=False)

        with pytest.raises(ValueError, match="ZIMBRA_PASSWORD"):
            ZimbraConfig.from_env()

    def test_direct_construction(self):
        cfg = ZimbraConfig(url="https://z.test", user="u", password="p")
        assert cfg.timeout == 30
