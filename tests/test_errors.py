"""Tests for Zimbra MCP error hierarchy."""

from zimbra_mcp.errors import (
    ZimbraAuthError,
    ZimbraConnectionError,
    ZimbraMCPError,
    ZimbraNotFoundError,
    ZimbraOperationError,
)


class TestErrorHierarchy:
    def test_all_inherit_from_base(self):
        for cls in (ZimbraConnectionError, ZimbraAuthError, ZimbraNotFoundError, ZimbraOperationError):
            assert issubclass(cls, ZimbraMCPError)

    def test_base_inherits_from_exception(self):
        assert issubclass(ZimbraMCPError, Exception)

    def test_distinct_types(self):
        classes = {ZimbraConnectionError, ZimbraAuthError, ZimbraNotFoundError, ZimbraOperationError}
        assert len(classes) == 4

    def test_catch_by_base(self):
        with pytest.raises(ZimbraMCPError):
            raise ZimbraNotFoundError("gone")

    def test_message_preserved(self):
        err = ZimbraOperationError("something broke")
        assert str(err) == "something broke"


import pytest
