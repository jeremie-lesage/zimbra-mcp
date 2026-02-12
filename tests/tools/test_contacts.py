"""Tests for contact tools."""

from unittest.mock import MagicMock

import pytest

from tests.conftest import capture_tools
from zimbra_mcp.tools.contacts import (
    _ATTR_MAP,
    _build_contact_attrs,
    _parse_contact,
    register_contact_tools,
)


class TestBuildContactAttrs:
    def test_basic_attrs(self):
        attrs = _build_contact_attrs(first_name="John", last_name="Doe", email="john@test.com")
        assert len(attrs) == 3
        names = {a["n"] for a in attrs}
        assert "firstName" in names
        assert "lastName" in names
        assert "email" in names

    def test_none_values_excluded(self):
        attrs = _build_contact_attrs(first_name="John", last_name=None)
        assert len(attrs) == 1
        assert attrs[0]["n"] == "firstName"

    def test_unknown_keys_ignored(self):
        attrs = _build_contact_attrs(first_name="John", unknown_field="value")
        assert len(attrs) == 1

    def test_empty(self):
        attrs = _build_contact_attrs()
        assert attrs == []


class TestParseContact:
    def test_basic_parse(self):
        cn = {
            "id": "100",
            "l": "7",
            "_attrs": {
                "firstName": "Alice",
                "lastName": "Smith",
                "email": "alice@test.com",
                "company": "Acme",
            },
        }
        result = _parse_contact(cn)
        assert result["id"] == "100"
        assert result["first_name"] == "Alice"
        assert result["last_name"] == "Smith"
        assert result["email"] == "alice@test.com"
        assert result["company"] == "Acme"

    def test_with_folder_lookup(self):
        cn = {"id": "101", "l": "7", "_attrs": {}}
        lookup = {"7": "USER_ROOT/Contacts"}
        result = _parse_contact(cn, folder_lookup=lookup)
        assert result["folder_path"] == "USER_ROOT/Contacts"

    def test_unknown_attrs_preserved(self):
        cn = {"id": "102", "_attrs": {"customField": "value"}}
        result = _parse_contact(cn)
        assert result["customField"] == "value"


@pytest.fixture
def contact_tools(connected_client):
    # Mock get_folder for the folder lookup cache
    connected_client.get_folder = MagicMock(return_value={
        "folder": {"id": "1", "name": "ROOT", "folder": [
            {"id": "7", "name": "Contacts"},
        ]}
    })
    tools = capture_tools(register_contact_tools, connected_client)
    return tools, connected_client


class TestSearchContacts:
    def test_search(self, contact_tools):
        tools, client = contact_tools
        client.search_contacts = MagicMock(return_value={
            "cn": [
                {"id": "100", "l": "7", "_attrs": {"firstName": "Alice", "email": "a@test.com"}},
            ],
            "total": 1,
            "more": False,
        })

        result = tools["search_contacts"]("Alice")
        assert len(result["contacts"]) == 1
        assert result["contacts"][0]["first_name"] == "Alice"

    def test_search_empty_query(self, contact_tools):
        tools, client = contact_tools
        client.search_contacts = MagicMock(return_value={"cn": [], "total": 0})

        result = tools["search_contacts"]()
        client.search_contacts.assert_called_once_with("*", limit=50, offset=0)


class TestGetContact:
    def test_get_contact(self, contact_tools):
        tools, client = contact_tools
        client.get_contact = MagicMock(return_value={
            "cn": {"id": "100", "l": "7", "_attrs": {"firstName": "Bob"}}
        })

        result = tools["get_contact"]("100")
        assert result["first_name"] == "Bob"


class TestCreateContact:
    def test_create(self, contact_tools):
        tools, client = contact_tools
        client.create_contact = MagicMock(return_value={
            "cn": {"id": "200", "l": "7", "_attrs": {"firstName": "New", "email": "new@test.com"}}
        })

        result = tools["create_contact"](first_name="New", email="new@test.com")
        assert result["success"] is True
        assert result["contact"]["first_name"] == "New"

    def test_create_empty_fails(self, contact_tools):
        tools, client = contact_tools

        result = tools["create_contact"]()
        assert result["success"] is False
        assert "At least one field" in result["error"]


class TestUpdateContact:
    def test_update(self, contact_tools):
        tools, client = contact_tools
        client.modify_contact = MagicMock(return_value={
            "cn": {"id": "100", "_attrs": {"firstName": "Updated"}}
        })

        result = tools["update_contact"]("100", first_name="Updated")
        assert result["success"] is True

    def test_update_empty_fails(self, contact_tools):
        tools, client = contact_tools

        result = tools["update_contact"]("100")
        assert result["success"] is False


class TestDeleteContact:
    def test_delete(self, contact_tools):
        tools, client = contact_tools
        client.delete_contacts = MagicMock()

        result = tools["delete_contact"](["100", "101"])
        assert result["success"] is True
        assert result["deleted_count"] == 2
        client.delete_contacts.assert_called_once_with(["100", "101"])
