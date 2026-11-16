"""Tests for filter tools."""

import copy
from unittest.mock import MagicMock

import pytest

from tests.conftest import capture_tools
from zimbra_mcp.config import ZimbraConfig
from zimbra_mcp.errors import ZimbraNotFoundError
from zimbra_mcp.tools.filters import (
    _build_actions,
    _build_tests,
    _single_condition,
    _summarize_rule,
    register_filter_tools,
)

COMPLEX_RULE = {
    "name": "Spam",
    "active": True,
    "filterTests": [{
        "condition": "anyof",
        "headerTest": [{"index": 0, "header": "X-VRSPAM-STATE", "stringComparison": "is", "value": "spam"}],
        "bodyTest": [{"index": 1, "value": "unsubscribe"}],
    }],
    "filterActions": [{
        "actionFileInto": [{"index": 0, "folderPath": "Junk", "copy": False}],
        "actionStop": [{"index": 1}],
    }],
}

NEWS_RULE = {
    "name": "News",
    "active": False,
    "filterTests": [{
        "condition": "allof",
        "addressTest": [{"index": 0, "header": "from", "part": "all", "stringComparison": "contains", "value": "news@a.com"}],
    }],
    "filterActions": [{
        "actionTag": [{"index": 0, "tagName": "news"}],
    }],
}


def _enabled():
    return ZimbraConfig(url="https://z.test", user="u", password="p", enable_filters=True)


@pytest.fixture
def filter_tools(connected_client):
    client = connected_client
    client.get_filter_rules = MagicMock(return_value=copy.deepcopy([COMPLEX_RULE, NEWS_RULE]))
    client.modify_filter_rules = MagicMock(return_value={})
    client.get_folder = MagicMock(return_value={"folder": {"id": "2"}})
    client.get_all_tags = MagicMock(return_value={"tag": [{"id": "1", "name": "news"}]})
    return capture_tools(register_filter_tools, client, _enabled()), client


def _written(client):
    return client.modify_filter_rules.call_args[0][0]


class TestRegistration:
    def test_read_only_by_default(self, connected_client):
        tools = capture_tools(register_filter_tools, connected_client)
        assert set(tools) == {"list_filters"}

    def test_read_only_when_disabled(self, connected_client):
        cfg = ZimbraConfig(url="https://z.test", user="u", password="p", enable_filters=False)
        tools = capture_tools(register_filter_tools, connected_client, cfg)
        assert set(tools) == {"list_filters"}

    def test_write_tools_when_enabled(self, connected_client):
        tools = capture_tools(register_filter_tools, connected_client, _enabled())
        assert set(tools) == {
            "list_filters", "add_filter", "update_filter", "delete_filter",
            "add_filter_condition", "remove_filter_condition",
        }

    def test_env_flag(self, monkeypatch):
        monkeypatch.setenv("ZIMBRA_URL", "https://z.test")
        monkeypatch.setenv("ZIMBRA_USER", "u")
        monkeypatch.setenv("ZIMBRA_PASSWORD", "p")
        monkeypatch.setenv("ZIMBRA_ENABLE_FILTERS", "true")
        assert ZimbraConfig.from_env().enable_filters is True


class TestClient:
    def test_get_filter_rules_single_dict(self, connected_client):
        connected_client.request = MagicMock(return_value={"filterRules": {"filterRule": NEWS_RULE}})
        assert connected_client.get_filter_rules() == [NEWS_RULE]

    def test_get_filter_rules_empty(self, connected_client):
        connected_client.request = MagicMock(return_value={"filterRules": {}})
        assert connected_client.get_filter_rules() == []

    def test_modify_sends_whole_list(self, connected_client):
        connected_client.request = MagicMock(return_value={})
        connected_client.modify_filter_rules([NEWS_RULE])
        connected_client.request.assert_called_once_with(
            "ModifyFilterRulesRequest", "urn:zimbraMail", {"filterRules": {"filterRule": [NEWS_RULE]}}
        )


class TestSummarize:
    def test_keeps_unknown_types_in_index_order(self):
        summary = _summarize_rule(COMPLEX_RULE)
        assert summary["match"] == "any"
        assert [c["type"] for c in summary["conditions"]] == ["headerTest", "bodyTest"]
        assert summary["conditions"][1] == {"type": "bodyTest", "value": "unsubscribe"}
        assert summary["actions"] == [
            {"type": "actionFileInto", "folderPath": "Junk", "copy": False},
            {"type": "actionStop"},
        ]

    def test_list_filters(self, filter_tools):
        tools, _ = filter_tools
        result = tools["list_filters"]()
        assert result["count"] == 2
        assert result["write_enabled"] is True
        assert result["filters"][1]["active"] is False


class TestBuildTests:
    def test_all_conditions(self):
        tests = _build_tests("bob@a.com", " Invoice ", "list.a.com", "any")
        assert tests == {
            "condition": "anyof",
            "addressTest": [{"index": 0, "header": "from", "stringComparison": "contains", "value": "bob@a.com", "part": "all"}],
            "headerTest": [
                {"index": 1, "header": "subject", "stringComparison": "contains", "value": "Invoice"},
                {"index": 2, "header": "List-Id", "stringComparison": "contains", "value": "list.a.com"},
            ],
        }

    def test_requires_a_condition(self):
        assert isinstance(_build_tests(None, " ", None, "all"), str)

    def test_invalid_match(self):
        assert isinstance(_build_tests("a", None, None, "some"), str)


class TestBuildActions:
    @pytest.fixture
    def client(self):
        client = MagicMock()
        client.get_all_tags.return_value = {"tag": {"id": "1", "name": "news"}}
        return client

    def test_all_actions_in_order(self, client):
        actions = _build_actions(client, "/Inbox/News/", "news", True, False, True)
        assert actions == {
            "actionFlag": [{"index": 0, "flagName": "read"}],
            "actionTag": [{"index": 1, "tagName": "news"}],
            "actionFileInto": [{"index": 2, "folderPath": "Inbox/News", "copy": False}],
            "actionStop": [{"index": 3}],
        }
        client.get_folder.assert_called_once_with("/Inbox/News")

    def test_trash_moves_to_trash(self, client):
        actions = _build_actions(client, None, None, False, True, False)
        assert actions == {"actionFileInto": [{"index": 0, "folderPath": "Trash", "copy": False}]}

    def test_never_discards(self, client):
        actions = _build_actions(client, None, None, True, True, True)
        assert "actionDiscard" not in actions

    def test_folder_and_trash_exclusive(self, client):
        assert isinstance(_build_actions(client, "Inbox", None, False, True, True), str)

    def test_requires_an_action(self, client):
        assert isinstance(_build_actions(client, None, None, False, False, True), str)

    def test_unknown_folder(self, client):
        client.get_folder.side_effect = ZimbraNotFoundError("no such folder path")
        assert "does not exist" in _build_actions(client, "Nope", None, False, False, True)

    def test_unknown_tag(self, client):
        assert "create_tag" in _build_actions(client, None, "missing", False, False, True)


class TestAddFilter:
    def test_appends_and_keeps_existing_rules(self, filter_tools):
        tools, client = filter_tools
        result = tools["add_filter"](name="Bob", sender="bob@a.com", folder="Inbox/Bob")
        assert result["success"] is True
        assert result["position"] == 3
        written = _written(client)
        assert written[:2] == [COMPLEX_RULE, NEWS_RULE]
        assert written[2]["name"] == "Bob"
        assert written[2]["active"] is True

    def test_duplicate_name(self, filter_tools):
        tools, client = filter_tools
        result = tools["add_filter"](name="News", sender="x", trash=True)
        assert result["success"] is False
        client.modify_filter_rules.assert_not_called()

    def test_empty_name(self, filter_tools):
        tools, client = filter_tools
        assert tools["add_filter"](name="  ", sender="x", trash=True)["success"] is False
        client.modify_filter_rules.assert_not_called()

    def test_invalid_action_writes_nothing(self, filter_tools):
        tools, client = filter_tools
        assert tools["add_filter"](name="X", sender="x")["success"] is False
        client.modify_filter_rules.assert_not_called()


class TestUpdateFilter:
    def test_toggle_active_keeps_everything_else(self, filter_tools):
        tools, client = filter_tools
        result = tools["update_filter"](name="Spam", active=False)
        assert result["success"] is True
        written = _written(client)
        assert written[0] == {**COMPLEX_RULE, "active": False}
        assert written[1] == NEWS_RULE

    def test_rename(self, filter_tools):
        tools, client = filter_tools
        tools["update_filter"](name="News", new_name="Newsletters")
        assert [r["name"] for r in _written(client)] == ["Spam", "Newsletters"]

    def test_rename_collision(self, filter_tools):
        tools, client = filter_tools
        assert tools["update_filter"](name="News", new_name="Spam")["success"] is False
        client.modify_filter_rules.assert_not_called()

    def test_replace_conditions_keeps_match_and_actions(self, filter_tools):
        tools, client = filter_tools
        tools["update_filter"](name="Spam", subject="promo")
        rule = _written(client)[0]
        assert rule["filterTests"] == [{
            "condition": "anyof",
            "headerTest": [{"index": 0, "header": "subject", "stringComparison": "contains", "value": "promo"}],
        }]
        assert rule["filterActions"] == COMPLEX_RULE["filterActions"]

    def test_replace_actions_keeps_conditions(self, filter_tools):
        tools, client = filter_tools
        tools["update_filter"](name="News", mark_read=True)
        rule = _written(client)[1]
        assert rule["filterTests"] == NEWS_RULE["filterTests"]
        assert rule["filterActions"] == [{
            "actionFlag": [{"index": 0, "flagName": "read"}],
            "actionStop": [{"index": 1}],
        }]

    def test_unknown_filter(self, filter_tools):
        tools, client = filter_tools
        assert tools["update_filter"](name="Nope", active=False)["success"] is False
        client.modify_filter_rules.assert_not_called()


class TestSingleCondition:
    def test_kinds(self):
        assert _single_condition("bob@a.com", None, None, None) == (
            "addressTest", {"header": "from", "part": "all", "stringComparison": "contains", "value": "bob@a.com"}
        )
        assert _single_condition(None, " a.com ", None, None)[1]["part"] == "domain"
        assert _single_condition(None, None, None, "l.a.com")[1]["header"] == "List-Id"

    def test_exactly_one(self):
        assert isinstance(_single_condition(None, None, None, None), str)
        assert isinstance(_single_condition("a", None, "b", None), str)


class TestAddFilterCondition:
    def test_appends_to_existing_conditions(self, filter_tools):
        tools, client = filter_tools
        result = tools["add_filter_condition"](name="Spam", sender_domain="spammer.com")
        assert result["success"] is True
        assert result["conditions_count"] == 3
        written = _written(client)
        block = written[0]["filterTests"][0]
        assert block["headerTest"] == COMPLEX_RULE["filterTests"][0]["headerTest"]
        assert block["bodyTest"] == COMPLEX_RULE["filterTests"][0]["bodyTest"]
        assert block["addressTest"] == [{
            "index": 2, "header": "from", "part": "domain", "stringComparison": "contains", "value": "spammer.com",
        }]
        assert block["condition"] == "anyof"
        assert written[0]["filterActions"] == COMPLEX_RULE["filterActions"]
        assert written[1] == NEWS_RULE

    def test_does_not_mutate_read_rules(self, filter_tools):
        tools, client = filter_tools
        rules = client.get_filter_rules.return_value
        tools["add_filter_condition"](name="News", subject="promo")
        assert rules[1] == NEWS_RULE

    def test_duplicate_is_refused(self, filter_tools):
        tools, client = filter_tools
        result = tools["add_filter_condition"](name="News", sender="NEWS@a.com")
        assert result["success"] is False
        client.modify_filter_rules.assert_not_called()

    def test_needs_exactly_one_condition(self, filter_tools):
        tools, client = filter_tools
        assert tools["add_filter_condition"](name="News", sender="a", subject="b")["success"] is False
        client.modify_filter_rules.assert_not_called()

    def test_unknown_filter(self, filter_tools):
        tools, client = filter_tools
        assert tools["add_filter_condition"](name="Nope", sender="a")["success"] is False
        client.modify_filter_rules.assert_not_called()


class TestRemoveFilterCondition:
    def test_removes_only_that_condition(self, filter_tools):
        tools, client = filter_tools
        result = tools["remove_filter_condition"](name="Spam", list_id="nope")
        assert result["success"] is False
        tools["add_filter_condition"](name="News", sender="other@a.com")
        client.get_filter_rules.return_value = _written(client)
        result = tools["remove_filter_condition"](name="News", sender="News@A.com")
        assert result["success"] is True
        assert result["conditions_count"] == 1
        block = _written(client)[1]["filterTests"][0]
        assert [t["value"] for t in block["addressTest"]] == ["other@a.com"]
        assert _written(client)[0] == COMPLEX_RULE

    def test_part_must_match(self, filter_tools):
        tools, client = filter_tools
        assert tools["remove_filter_condition"](name="News", sender_domain="news@a.com")["success"] is False
        client.modify_filter_rules.assert_not_called()

    def test_last_condition_is_kept(self, filter_tools):
        tools, client = filter_tools
        result = tools["remove_filter_condition"](name="News", sender="news@a.com")
        assert result["success"] is False
        assert "delete_filter" in result["error"]
        client.modify_filter_rules.assert_not_called()


class TestDeleteFilter:
    def test_removes_only_that_filter(self, filter_tools):
        tools, client = filter_tools
        result = tools["delete_filter"](name="Spam")
        assert result["success"] is True
        assert result["deleted"]["name"] == "Spam"
        assert _written(client) == [NEWS_RULE]

    def test_unknown_filter(self, filter_tools):
        tools, client = filter_tools
        assert tools["delete_filter"](name="Nope")["success"] is False
        client.modify_filter_rules.assert_not_called()
