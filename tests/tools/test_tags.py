"""Tests for tag tools."""

from unittest.mock import MagicMock

import pytest

from tests.conftest import capture_tools
from zimbra_mcp.tools.tags import (
    ZIMBRA_COLORS,
    _color_id_to_name,
    register_tag_tools,
)


class TestColorMapping:
    def test_known_colors(self):
        assert _color_id_to_name(1) == "blue"
        assert _color_id_to_name(5) == "red"
        assert _color_id_to_name(9) == "orange"

    def test_none(self):
        assert _color_id_to_name(None) is None

    def test_unknown_color(self):
        assert _color_id_to_name(99) == "custom_99"

    def test_all_colors_have_ids(self):
        for name, cid in ZIMBRA_COLORS.items():
            assert _color_id_to_name(cid) == name


@pytest.fixture
def tag_tools(connected_client):
    tools = capture_tools(register_tag_tools, connected_client)
    return tools, connected_client


class TestListTags:
    def test_list_tags(self, tag_tools):
        tools, client = tag_tools
        client.get_all_tags = MagicMock(return_value={
            "tag": [
                {"id": "1", "name": "urgent", "color": 5, "u": 3, "n": 10},
                {"id": "2", "name": "work", "color": 1},
            ]
        })

        result = tools["list_tags"]()
        assert len(result["tags"]) == 2
        assert result["tags"][0]["name"] == "urgent"
        assert result["tags"][0]["color_name"] == "red"
        assert result["tags"][1]["color_name"] == "blue"
        assert "available_colors" in result

    def test_list_tags_empty(self, tag_tools):
        tools, client = tag_tools
        client.get_all_tags = MagicMock(return_value={})

        result = tools["list_tags"]()
        assert result["tags"] == []

    def test_list_tags_single_dict(self, tag_tools):
        tools, client = tag_tools
        client.get_all_tags = MagicMock(return_value={
            "tag": {"id": "1", "name": "solo"}
        })

        result = tools["list_tags"]()
        assert len(result["tags"]) == 1


class TestCreateTag:
    def test_create_tag_with_color(self, tag_tools):
        tools, client = tag_tools
        client.create_tag = MagicMock(return_value={
            "tag": {"id": "10", "name": "test", "color": 3}
        })

        result = tools["create_tag"]("test", color="green")
        assert result["success"] is True
        assert result["tag"]["name"] == "test"
        client.create_tag.assert_called_once_with("test", color=3)

    def test_create_tag_without_color(self, tag_tools):
        tools, client = tag_tools
        client.create_tag = MagicMock(return_value={
            "tag": {"id": "11", "name": "plain"}
        })

        result = tools["create_tag"]("plain")
        assert result["success"] is True
        client.create_tag.assert_called_once_with("plain", color=None)

    def test_create_tag_invalid_color(self, tag_tools):
        tools, client = tag_tools

        result = tools["create_tag"]("test", color="rainbow")
        assert result["success"] is False
        assert "Invalid color" in result["error"]


class TestDeleteTag:
    def test_delete_tag(self, tag_tools):
        tools, client = tag_tools
        client.delete_tag = MagicMock()

        result = tools["delete_tag"]("5")
        assert result["success"] is True
        assert result["deleted_tag_id"] == "5"
        client.delete_tag.assert_called_once_with("5")


class TestAddTagToEmails:
    def test_add_tag(self, tag_tools):
        tools, client = tag_tools
        client.tag_messages = MagicMock(return_value={"action": {}})

        result = tools["add_tag_to_emails"](["1", "2"], "urgent")
        assert result["success"] is True
        assert result["tagged_count"] == 2
        client.tag_messages.assert_called_once_with(["1", "2"], "urgent", untag=False)


class TestRemoveTagFromEmails:
    def test_remove_tag(self, tag_tools):
        tools, client = tag_tools
        client.tag_messages = MagicMock(return_value={"action": {}})

        result = tools["remove_tag_from_emails"](["3"], "old")
        assert result["success"] is True
        assert result["untagged_count"] == 1
        client.tag_messages.assert_called_once_with(["3"], "old", untag=True)
