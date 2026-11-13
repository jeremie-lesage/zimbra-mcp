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
        assert cfg.enable_send is False

    @patch("zimbra_mcp.config.load_dotenv")
    def test_enable_send_true(self, _mock_dotenv, monkeypatch):
        monkeypatch.setenv("ZIMBRA_URL", "https://z.test/service/soap")
        monkeypatch.setenv("ZIMBRA_USER", "u@test.com")
        monkeypatch.setenv("ZIMBRA_PASSWORD", "pw")
        monkeypatch.setenv("ZIMBRA_ENABLE_SEND", "true")

        cfg = ZimbraConfig.from_env()
        assert cfg.enable_send is True

    @patch("zimbra_mcp.config.load_dotenv")
    def test_enable_send_yes(self, _mock_dotenv, monkeypatch):
        monkeypatch.setenv("ZIMBRA_URL", "https://z.test/service/soap")
        monkeypatch.setenv("ZIMBRA_USER", "u@test.com")
        monkeypatch.setenv("ZIMBRA_PASSWORD", "pw")
        monkeypatch.setenv("ZIMBRA_ENABLE_SEND", "yes")

        cfg = ZimbraConfig.from_env()
        assert cfg.enable_send is True

    @patch("zimbra_mcp.config.load_dotenv")
    def test_enable_send_1(self, _mock_dotenv, monkeypatch):
        monkeypatch.setenv("ZIMBRA_URL", "https://z.test/service/soap")
        monkeypatch.setenv("ZIMBRA_USER", "u@test.com")
        monkeypatch.setenv("ZIMBRA_PASSWORD", "pw")
        monkeypatch.setenv("ZIMBRA_ENABLE_SEND", "1")

        cfg = ZimbraConfig.from_env()
        assert cfg.enable_send is True

    @patch("zimbra_mcp.config.load_dotenv")
    def test_enable_send_default_false(self, _mock_dotenv, monkeypatch):
        monkeypatch.setenv("ZIMBRA_URL", "https://z.test/service/soap")
        monkeypatch.setenv("ZIMBRA_USER", "u@test.com")
        monkeypatch.setenv("ZIMBRA_PASSWORD", "pw")
        monkeypatch.delenv("ZIMBRA_ENABLE_SEND", raising=False)

        cfg = ZimbraConfig.from_env()
        assert cfg.enable_send is False


class TestConfigSecurity:
    def test_plain_http_refused(self):
        with pytest.raises(ValueError, match="HTTP"):
            ZimbraConfig(url="http://z.test/service/soap", user="u", password="p")

    def test_plain_http_opt_in(self):
        cfg = ZimbraConfig(url="http://z.test/service/soap", user="u", password="p", allow_insecure_http=True)
        assert cfg.base_url == "http://z.test"

    def test_invalid_scheme_refused(self):
        with pytest.raises(ValueError):
            ZimbraConfig(url="file:///etc/passwd", user="u", password="p")

    def test_password_not_in_repr(self):
        cfg = ZimbraConfig(url="https://z.test/service/soap", user="u", password="hunter2")
        assert "hunter2" not in repr(cfg)

    def test_base_url(self):
        cfg = ZimbraConfig(url="https://z.test:8443/service/soap/", user="u", password="p")
        assert cfg.base_url == "https://z.test:8443"

    def test_safe_defaults(self):
        cfg = ZimbraConfig(url="https://z.test/service/soap", user="u", password="p")
        assert cfg.enable_hard_delete is False
        assert cfg.download_dir is None
        assert cfg.max_attachment_bytes == 50 * 1024 * 1024

    @patch("zimbra_mcp.config.load_dotenv")
    def test_from_env_security_options(self, _mock_dotenv, monkeypatch, tmp_path):
        monkeypatch.setenv("ZIMBRA_URL", "http://z.test/service/soap")
        monkeypatch.setenv("ZIMBRA_USER", "u")
        monkeypatch.setenv("ZIMBRA_PASSWORD", "p")
        monkeypatch.setenv("ZIMBRA_ALLOW_INSECURE_HTTP", "true")
        monkeypatch.setenv("ZIMBRA_ENABLE_HARD_DELETE", "true")
        monkeypatch.setenv("ZIMBRA_DOWNLOAD_DIR", str(tmp_path))
        monkeypatch.setenv("ZIMBRA_MAX_ATTACHMENT_MB", "5")

        cfg = ZimbraConfig.from_env()
        assert cfg.allow_insecure_http is True
        assert cfg.enable_hard_delete is True
        assert cfg.download_dir == tmp_path.resolve()
        assert cfg.max_attachment_bytes == 5 * 1024 * 1024

    @patch("zimbra_mcp.config.load_dotenv")
    def test_invalid_timeout(self, _mock_dotenv, monkeypatch):
        monkeypatch.setenv("ZIMBRA_URL", "https://z.test/service/soap")
        monkeypatch.setenv("ZIMBRA_USER", "u")
        monkeypatch.setenv("ZIMBRA_PASSWORD", "p")
        monkeypatch.setenv("ZIMBRA_TIMEOUT", "abc")
        with pytest.raises(ValueError, match="ZIMBRA_TIMEOUT"):
            ZimbraConfig.from_env()
