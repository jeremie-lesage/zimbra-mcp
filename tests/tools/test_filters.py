"""Tests for filter tools."""

import asyncio
import copy
import json
from unittest.mock import MagicMock

import pytest
from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError

from tests.conftest import capture_tools
from zimbra_mcp.config import ZimbraConfig
from zimbra_mcp.errors import ZimbraNotFoundError
from zimbra_mcp.tools.filters import (
    FilterCondition,
    _build_actions,
    _build_tests,
    _evaluate_rule,
    _evaluate_test,
    _parse_condition,
    _summarize_rule,
    _target_index,
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
        assert set(tools) == {"list_filters", "find_matching_filters"}

    def test_read_only_when_disabled(self, connected_client):
        cfg = ZimbraConfig(url="https://z.test", user="u", password="p", enable_filters=False)
        tools = capture_tools(register_filter_tools, connected_client, cfg)
        assert set(tools) == {"list_filters", "find_matching_filters"}

    def test_write_tools_when_enabled(self, connected_client):
        tools = capture_tools(register_filter_tools, connected_client, _enabled())
        assert set(tools) == {
            "list_filters", "find_matching_filters", "add_filter", "update_filter", "delete_filter",
            "add_filter_condition", "remove_filter_condition", "move_filter",
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


def _c(field, value, **extra):
    return {"field": field, "value": value, **extra}


class TestParseCondition:
    def test_sender_and_recipient_are_address_tests(self):
        assert _parse_condition(_c("sender", " bob@a.com ")) == (
            "addressTest", {"header": "from", "part": "all", "stringComparison": "contains", "value": "bob@a.com"}
        )
        assert _parse_condition(_c("Recipient", "atos.net", part="domain", comparison="is")) == (
            "addressTest", {"header": "to,cc", "part": "domain", "stringComparison": "is", "value": "atos.net"}
        )

    def test_known_and_custom_headers(self):
        assert _parse_condition(_c("list_id", "l.a.com"))[1]["header"] == "List-Id"
        assert _parse_condition(_c("subject", "x"))[1]["header"] == "subject"
        assert _parse_condition(_c("X-VRSPAM-STATE", "spam", comparison="is")) == (
            "headerTest", {"header": "X-VRSPAM-STATE", "stringComparison": "is", "value": "spam"}
        )

    def test_accepts_model(self):
        assert _parse_condition(FilterCondition(field="sender", value="a"))[0] == "addressTest"

    @pytest.mark.parametrize("spec", [
        _c("sender", "  "),
        _c("subject", "x", part="domain"),
        _c("X Spam", "x"),
        _c("x,from", "x"),
        _c("sender", "x", comparison="matches"),
        {"value": "x"},
    ])
    def test_invalid(self, spec):
        assert isinstance(_parse_condition(spec), str)


class TestBuildTests:
    def test_groups_by_kind_with_global_index(self):
        tests = _build_tests([_c("sender", "bob@a.com"), _c("subject", "Invoice"), _c("list_id", "list.a.com")], "any")
        assert tests == {
            "condition": "anyof",
            "addressTest": [{"index": 0, "header": "from", "part": "all", "stringComparison": "contains", "value": "bob@a.com"}],
            "headerTest": [
                {"index": 1, "header": "subject", "stringComparison": "contains", "value": "Invoice"},
                {"index": 2, "header": "List-Id", "stringComparison": "contains", "value": "list.a.com"},
            ],
        }

    def test_requires_a_condition(self):
        assert isinstance(_build_tests([], "all"), str)

    def test_invalid_condition(self):
        assert isinstance(_build_tests([_c("sender", "a"), _c("bad field", "b")], "all"), str)

    def test_invalid_match(self):
        assert isinstance(_build_tests([_c("sender", "a")], "some"), str)


class TestBuildActions:
    @pytest.fixture
    def client(self):
        client = MagicMock()
        client.get_all_tags.return_value = {"tag": {"id": "1", "name": "news"}}
        return client

    def _build(self, client, folder=None, tag=None, mark_read=False, flag=False, keep=False, trash=False, stop=True):
        return _build_actions(client, folder, tag, mark_read, flag, keep, trash, stop)

    def test_all_actions_in_order(self, client):
        actions = self._build(client, "/Inbox/News/", "news", mark_read=True, flag=True, keep=True)
        assert actions == {
            "actionFlag": [{"index": 0, "flagName": "read"}, {"index": 1, "flagName": "flagged"}],
            "actionTag": [{"index": 2, "tagName": "news"}],
            "actionKeep": [{"index": 3}],
            "actionFileInto": [{"index": 4, "folderPath": "Inbox/News", "copy": False}],
            "actionStop": [{"index": 5}],
        }
        client.get_folder.assert_called_once_with("/Inbox/News")

    def test_flag_alone(self, client):
        assert self._build(client, flag=True, stop=False) == {"actionFlag": [{"index": 0, "flagName": "flagged"}]}

    def test_trash_moves_to_trash(self, client):
        actions = self._build(client, trash=True, stop=False)
        assert actions == {"actionFileInto": [{"index": 0, "folderPath": "Trash", "copy": False}]}

    def test_never_discards_redirects_or_replies(self, client):
        actions = self._build(client, "Inbox", "news", True, True, True)
        assert not {"actionDiscard", "actionRedirect", "actionReply", "actionNotify"} & set(actions)

    def test_exclusive_actions(self, client):
        assert isinstance(self._build(client, "Inbox", trash=True), str)
        assert isinstance(self._build(client, keep=True, trash=True), str)

    def test_requires_an_action(self, client):
        assert isinstance(self._build(client), str)

    def test_unknown_folder(self, client):
        client.get_folder.side_effect = ZimbraNotFoundError("no such folder path")
        assert "does not exist" in self._build(client, "Nope")

    def test_unknown_tag(self, client):
        assert "create_tag" in self._build(client, tag="missing")


class TestAddFilter:
    def test_appends_and_keeps_existing_rules(self, filter_tools):
        tools, client = filter_tools
        result = tools["add_filter"](name="Bob", conditions=[_c("sender", "bob@a.com")], folder="Inbox/Bob")
        assert result["success"] is True
        assert result["position"] == 3
        written = _written(client)
        assert written[:2] == [COMPLEX_RULE, NEWS_RULE]
        assert written[2]["name"] == "Bob"
        assert written[2]["active"] is True

    def test_advanced_conditions(self, filter_tools):
        tools, client = filter_tools
        tools["add_filter"](
            name="VRSPAM",
            conditions=[_c("X-VRSPAM-STATE", "spam", comparison="is"), _c("recipient", "atos.net", part="domain")],
            match="any", folder="Junk", flag=True,
        )
        rule = _written(client)[2]
        assert rule["filterTests"] == [{
            "condition": "anyof",
            "headerTest": [{"index": 0, "header": "X-VRSPAM-STATE", "stringComparison": "is", "value": "spam"}],
            "addressTest": [{"index": 1, "header": "to,cc", "part": "domain", "stringComparison": "contains", "value": "atos.net"}],
        }]

    def test_duplicate_name(self, filter_tools):
        tools, client = filter_tools
        result = tools["add_filter"](name="News", conditions=[_c("sender", "x")], trash=True)
        assert result["success"] is False
        client.modify_filter_rules.assert_not_called()

    def test_empty_name(self, filter_tools):
        tools, client = filter_tools
        assert tools["add_filter"](name="  ", conditions=[_c("sender", "x")], trash=True)["success"] is False
        client.modify_filter_rules.assert_not_called()

    def test_invalid_action_writes_nothing(self, filter_tools):
        tools, client = filter_tools
        assert tools["add_filter"](name="X", conditions=[_c("sender", "x")])["success"] is False
        client.modify_filter_rules.assert_not_called()


class TestTargetIndex:
    RULES = [{"name": "A"}, {"name": "B"}, {"name": "C"}]

    def test_default_is_end(self):
        assert _target_index(self.RULES, None, None) == 3

    def test_before(self):
        assert _target_index(self.RULES, "B", None) == 1

    def test_position_is_one_based_and_clamped(self):
        assert _target_index(self.RULES, None, 1) == 0
        assert _target_index(self.RULES, None, 99) == 3

    def test_errors(self):
        assert isinstance(_target_index(self.RULES, "Nope", None), str)
        assert isinstance(_target_index(self.RULES, None, 0), str)
        assert isinstance(_target_index(self.RULES, "A", 1), str)


class TestAddFilterInvalidCondition:
    def test_writes_nothing(self, filter_tools):
        tools, client = filter_tools
        assert tools["add_filter"](name="X", conditions=[], folder="Inbox")["success"] is False
        assert tools["add_filter"](name="X", conditions=[_c("sender", "a")], match="some", folder="Inbox")["success"] is False
        assert tools["add_filter"](name="X", conditions=[_c("bad field", "a")], folder="Inbox")["success"] is False
        client.modify_filter_rules.assert_not_called()


class TestAddFilterPlacement:
    def test_before(self, filter_tools):
        tools, client = filter_tools
        result = tools["add_filter"](name="Bob", conditions=[_c("sender", "bob@a.com")], trash=True, before="Spam")
        assert [r["name"] for r in _written(client)] == ["Bob", "Spam", "News"]
        assert (result["position"], result["after"], result["before"]) == (1, None, "Spam")

    def test_position(self, filter_tools):
        tools, client = filter_tools
        result = tools["add_filter"](name="Bob", conditions=[_c("sender", "bob@a.com")], trash=True, position=2)
        assert [r["name"] for r in _written(client)] == ["Spam", "Bob", "News"]
        assert (result["after"], result["before"]) == ("Spam", "News")

    def test_unknown_before_writes_nothing(self, filter_tools):
        tools, client = filter_tools
        result = tools["add_filter"](name="Bob", conditions=[_c("sender", "b")], trash=True, before="Nope")
        assert result["success"] is False
        client.modify_filter_rules.assert_not_called()


class TestMoveFilter:
    def test_move_before(self, filter_tools):
        tools, client = filter_tools
        result = tools["move_filter"](name="News", before="Spam")
        assert _written(client) == [NEWS_RULE, COMPLEX_RULE]
        assert (result["previous_position"], result["position"]) == (2, 1)

    def test_move_to_position(self, filter_tools):
        tools, client = filter_tools
        tools["move_filter"](name="Spam", position=99)
        assert _written(client) == [NEWS_RULE, COMPLEX_RULE]

    def test_needs_exactly_one_target(self, filter_tools):
        tools, client = filter_tools
        assert tools["move_filter"](name="Spam")["success"] is False
        assert tools["move_filter"](name="Spam", before="News", position=1)["success"] is False
        assert tools["move_filter"](name="Spam", before="Spam")["success"] is False
        client.modify_filter_rules.assert_not_called()

    def test_unknown_filter(self, filter_tools):
        tools, client = filter_tools
        assert tools["move_filter"](name="Nope", position=1)["success"] is False
        assert tools["move_filter"](name="Spam", before="Nope")["success"] is False
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
        tools["update_filter"](name="Spam", conditions=[_c("subject", "promo")])
        rule = _written(client)[0]
        assert rule["filterTests"] == [{
            "condition": "anyof",
            "headerTest": [{"index": 0, "header": "subject", "stringComparison": "contains", "value": "promo"}],
        }]
        assert rule["filterActions"] == COMPLEX_RULE["filterActions"]

    def test_match_alone_keeps_conditions(self, filter_tools):
        tools, client = filter_tools
        rules = client.get_filter_rules.return_value
        tools["update_filter"](name="Spam", match="all")
        tests = _written(client)[0]["filterTests"][0]
        assert tests == {**COMPLEX_RULE["filterTests"][0], "condition": "allof"}
        assert rules[0] == COMPLEX_RULE

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

    def test_invalid_input_writes_nothing(self, filter_tools):
        tools, client = filter_tools
        assert tools["update_filter"](name="News", new_name="  ")["success"] is False
        assert tools["update_filter"](name="News", match="some")["success"] is False
        assert tools["update_filter"](name="News", conditions=[])["success"] is False
        assert tools["update_filter"](name="News", folder="Inbox", trash=True)["success"] is False
        client.modify_filter_rules.assert_not_called()

    def test_valid_change_is_not_written_when_another_is_invalid(self, filter_tools):
        tools, client = filter_tools
        result = tools["update_filter"](name="News", active=True, conditions=[_c("sender", "x")], match="some")
        assert result["success"] is False
        client.modify_filter_rules.assert_not_called()

    def test_match_alone_on_filter_without_condition_block(self, filter_tools):
        tools, client = filter_tools
        client.get_filter_rules.return_value = [{"name": "Empty", "active": True, "filterActions": []}]
        assert tools["update_filter"](name="Empty", match="any")["success"] is False
        client.modify_filter_rules.assert_not_called()


class TestAddFilterCondition:
    def test_appends_to_existing_conditions(self, filter_tools):
        tools, client = filter_tools
        result = tools["add_filter_condition"](name="Spam", condition=_c("sender", "spammer.com", part="domain"))
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

    def test_custom_header_with_is(self, filter_tools):
        tools, client = filter_tools
        tools["add_filter_condition"](name="Spam", condition=_c("X-Spam-Flag", "YES", comparison="is"))
        assert _written(client)[0]["filterTests"][0]["headerTest"][-1] == {
            "index": 2, "header": "X-Spam-Flag", "stringComparison": "is", "value": "YES",
        }

    def test_does_not_mutate_read_rules(self, filter_tools):
        tools, client = filter_tools
        rules = client.get_filter_rules.return_value
        tools["add_filter_condition"](name="News", condition=_c("subject", "promo"))
        assert rules[1] == NEWS_RULE

    def test_duplicate_is_refused(self, filter_tools):
        tools, client = filter_tools
        result = tools["add_filter_condition"](name="News", condition=_c("sender", "NEWS@a.com"))
        assert result["success"] is False
        client.modify_filter_rules.assert_not_called()

    def test_invalid_condition(self, filter_tools):
        tools, client = filter_tools
        assert tools["add_filter_condition"](name="News", condition=_c("bad field", "a"))["success"] is False
        client.modify_filter_rules.assert_not_called()

    def test_unknown_filter(self, filter_tools):
        tools, client = filter_tools
        assert tools["add_filter_condition"](name="Nope", condition=_c("sender", "a"))["success"] is False
        client.modify_filter_rules.assert_not_called()


class TestRemoveFilterCondition:
    def test_removes_only_that_condition(self, filter_tools):
        tools, client = filter_tools
        result = tools["remove_filter_condition"](name="Spam", condition=_c("list_id", "nope"))
        assert result["success"] is False
        tools["add_filter_condition"](name="News", condition=_c("sender", "other@a.com"))
        client.get_filter_rules.return_value = _written(client)
        result = tools["remove_filter_condition"](name="News", condition=_c("sender", "News@A.com"))
        assert result["success"] is True
        assert result["conditions_count"] == 1
        block = _written(client)[1]["filterTests"][0]
        assert [t["value"] for t in block["addressTest"]] == ["other@a.com"]
        assert _written(client)[0] == COMPLEX_RULE

    def test_found_whatever_the_comparison(self, filter_tools):
        tools, client = filter_tools
        result = tools["remove_filter_condition"](name="Spam", condition=_c("x-vrspam-state", "SPAM"))
        assert result["success"] is True
        assert "headerTest" not in _written(client)[0]["filterTests"][0]

    def test_part_must_match(self, filter_tools):
        tools, client = filter_tools
        result = tools["remove_filter_condition"](name="News", condition=_c("sender", "news@a.com", part="domain"))
        assert result["success"] is False
        client.modify_filter_rules.assert_not_called()

    def test_last_condition_is_kept(self, filter_tools):
        tools, client = filter_tools
        result = tools["remove_filter_condition"](name="News", condition=_c("sender", "news@a.com"))
        assert result["success"] is False
        assert "delete_filter" in result["error"]
        client.modify_filter_rules.assert_not_called()

    def test_invalid_input_writes_nothing(self, filter_tools):
        tools, client = filter_tools
        assert tools["remove_filter_condition"](name="News", condition=_c("sender", " "))["success"] is False
        assert tools["remove_filter_condition"](name="Nope", condition=_c("sender", "news@a.com"))["success"] is False
        client.modify_filter_rules.assert_not_called()

    def test_filter_without_condition_block(self, filter_tools):
        tools, client = filter_tools
        client.get_filter_rules.return_value = [{"name": "Empty", "active": True, "filterActions": []}]
        assert tools["add_filter_condition"](name="Empty", condition=_c("sender", "a"))["success"] is False
        client.modify_filter_rules.assert_not_called()


def _rule(name, condition, tests, stop=True, active=True):
    actions = {"actionFileInto": [{"index": 0, "folderPath": name}]}
    if stop:
        actions["actionStop"] = [{"index": 1}]
    return {"name": name, "active": active, "filterTests": [{"condition": condition, **tests}], "filterActions": [actions]}


def _addr(value, part="all", comparison="contains", **extra):
    return {"index": 0, "header": "from", "part": part, "stringComparison": comparison, "value": value, **extra}


def _hdr(header, value, comparison="contains", **extra):
    return {"index": 0, "header": header, "stringComparison": comparison, "value": value, **extra}


class TestEvaluateTest:
    HEADERS = {
        "from": ["Bob Martin <Bob@Spammer.com>"],
        "subject": ["=?utf-8?q?Offre_sp=C3=A9ciale?="],
        "list-id": ["<news.spammer.com>"],
    }

    @pytest.mark.parametrize("entry,expected", [
        (_addr("spammer.com", part="domain"), True),
        (_addr("bob", part="localpart", comparison="is"), True),
        (_addr("bob@spammer.com", comparison="is"), True),
        (_addr("martin"), False),
        (_addr("*@spammer.*", comparison="matches"), True),
        (_addr("b?b@*", comparison="matches"), True),
        (_addr("Bob", caseSensitive=False), True),
        (_addr("bob", caseSensitive=True), False),
        (_addr("spammer.com", part="domain", negative=True), False),
    ])
    def test_address(self, entry, expected):
        assert _evaluate_test("addressTest", entry, self.HEADERS) is expected

    def test_header_decodes_encoded_words(self):
        assert _evaluate_test("headerTest", _hdr("subject", "spéciale"), self.HEADERS) is True

    def test_invalid_encoded_word_is_kept_as_is(self):
        headers = {"subject": ["=?unknown-charset?q?abc?="]}
        assert _evaluate_test("headerTest", _hdr("subject", "unknown-charset"), headers) is True

    def test_header_name_is_case_insensitive_and_can_be_a_list(self):
        assert _evaluate_test("headerTest", _hdr("List-ID", "news.spammer"), self.HEADERS) is True
        assert _evaluate_test("headerTest", _hdr("to,list-id", "news.spammer"), self.HEADERS) is True

    def test_missing_header(self):
        assert _evaluate_test("headerTest", _hdr("X-Spam", "yes"), self.HEADERS) is False
        assert _evaluate_test("headerTest", _hdr("X-Spam", "yes", negative=True), self.HEADERS) is True

    def test_exists(self):
        assert _evaluate_test("existsTest", {"header": "list-id"}, self.HEADERS) is True
        assert _evaluate_test("existsTest", {"header": "x-spam"}, self.HEADERS) is False

    def test_unsupported(self):
        assert _evaluate_test("bodyTest", {"value": "x"}, self.HEADERS) is None
        assert _evaluate_test("headerTest", {"header": "subject", "countComparison": "gt", "value": "1"}, self.HEADERS) is None


class TestEvaluateRule:
    HEADERS = {"from": ["bob@spammer.com"], "subject": ["Hello"]}

    def test_anyof(self):
        rule = _rule("R", "anyof", {"addressTest": [_addr("other.com"), _addr("spammer.com")]})
        result, matched, unsupported = _evaluate_rule(rule, self.HEADERS)
        assert result is True
        assert [m["value"] for m in matched] == ["spammer.com"]
        assert unsupported == []

    def test_allof(self):
        rule = _rule("R", "allof", {"addressTest": [_addr("spammer.com")], "headerTest": [_hdr("subject", "promo")]})
        assert _evaluate_rule(rule, self.HEADERS)[0] is False

    def test_unknown_propagates(self):
        anyof = _rule("R", "anyof", {"addressTest": [_addr("other.com")], "bodyTest": [{"value": "x"}]})
        assert _evaluate_rule(anyof, self.HEADERS)[0] is None
        assert _evaluate_rule(anyof, self.HEADERS)[2] == ["bodyTest"]
        allof = _rule("R", "allof", {"addressTest": [_addr("spammer.com")], "bodyTest": [{"value": "x"}]})
        assert _evaluate_rule(allof, self.HEADERS)[0] is None

    def test_known_result_wins_over_unknown(self):
        anyof = _rule("R", "anyof", {"addressTest": [_addr("spammer.com")], "bodyTest": [{"value": "x"}]})
        assert _evaluate_rule(anyof, self.HEADERS)[0] is True
        allof = _rule("R", "allof", {"addressTest": [_addr("other.com")], "bodyTest": [{"value": "x"}]})
        assert _evaluate_rule(allof, self.HEADERS)[0] is False


class TestFindMatchingFilters:
    RULES = [
        _rule("Inactive", "anyof", {"addressTest": [_addr("spammer.com")]}, active=False),
        _rule("Body", "anyof", {"bodyTest": [{"index": 0, "value": "promo"}]}),
        _rule("Tag only", "anyof", {"addressTest": [_addr("spammer.com", part="domain")]}, stop=False),
        _rule("SPAM", "anyof", {"addressTest": [_addr("nope.com"), _addr("spammer.com")]}),
        _rule("Later", "anyof", {"addressTest": [_addr("spammer.com")]}),
        _rule("Other", "anyof", {"addressTest": [_addr("other.com")]}),
    ]

    @pytest.fixture
    def tools(self, connected_client):
        connected_client.get_filter_rules = MagicMock(return_value=self.RULES)
        connected_client.get_message_headers = MagicMock(return_value={"from": ["Bob <bob@spammer.com>"]})
        return capture_tools(register_filter_tools, connected_client), connected_client

    def test_registered_without_write_flag(self, tools):
        assert "find_matching_filters" in tools[0]

    def test_hypothetical_sender(self, tools):
        tools, _ = tools
        result = tools["find_matching_filters"](sender="bob@spammer.com")
        assert [(m["name"], m["result"], m["stops"]) for m in result["matches"]] == [
            ("Body", "unknown", True),
            ("Tag only", "match", False),
            ("SPAM", "match", True),
        ]
        assert result["stopped_by"] == "SPAM"
        assert result["not_reached"] == 2
        assert result["matches"][2]["position"] == 4
        assert [c["value"] for c in result["matches"][2]["matched_conditions"]] == ["spammer.com"]

    def test_no_match(self, tools):
        tools, _ = tools
        result = tools["find_matching_filters"](sender="alice@example.org")
        assert [m["name"] for m in result["matches"]] == ["Body"]
        assert result["stopped_by"] is None
        assert result["not_reached"] == 0

    def test_message_requests_only_used_headers(self, tools):
        tools, client = tools
        result = tools["find_matching_filters"](msg_id="42")
        client.get_message_headers.assert_called_once_with("42", ["from", "subject"])
        assert result["stopped_by"] == "SPAM"

    def test_needs_exactly_one_source(self, tools):
        tools, _ = tools
        assert tools["find_matching_filters"]()["success"] is False
        assert tools["find_matching_filters"](msg_id="1", sender="a@b.c")["success"] is False

    def test_hypothetical_subject_and_list_id(self, connected_client):
        rules = [
            _rule("Promo", "allof", {"addressTest": [_addr("shop.com")], "headerTest": [_hdr("subject", "promo")]}),
            _rule("List", "anyof", {"headerTest": [_hdr("List-Id", "news.shop.com")]}),
        ]
        connected_client.get_filter_rules = MagicMock(return_value=rules)
        tools = capture_tools(register_filter_tools, connected_client)
        find = tools["find_matching_filters"]

        assert find(sender="a@shop.com")["matches"] == []
        result = find(sender="a@shop.com", subject="Big PROMO")
        assert result["stopped_by"] == "Promo"
        assert result["email"]["subject"] == ["Big PROMO"]
        result = find(sender="a@other.com", list_id="<news.shop.com>")
        assert result["stopped_by"] == "List"
        assert result["email"]["list_id"] == ["<news.shop.com>"]

    def test_hypothetical_recipient(self, connected_client):
        rules = [_rule("Atos", "anyof", {"addressTest": [{**_addr("atos.net", part="domain"), "header": "to,cc"}]})]
        connected_client.get_filter_rules = MagicMock(return_value=rules)
        find = capture_tools(register_filter_tools, connected_client)["find_matching_filters"]
        assert find(sender="a@b.com")["stopped_by"] is None
        result = find(sender="a@b.com", recipient="Bob <bob@atos.net>")
        assert result["stopped_by"] == "Atos"
        assert result["email"]["to"] == ["Bob <bob@atos.net>"]


class TestFastMCPIntegration:
    @pytest.fixture
    def server(self, connected_client):
        connected_client.get_filter_rules = MagicMock(return_value=copy.deepcopy([NEWS_RULE]))
        connected_client.modify_filter_rules = MagicMock(return_value={})
        connected_client.get_folder = MagicMock(return_value={"folder": {"id": "4"}})
        server = FastMCP("test")
        register_filter_tools(server, connected_client, _enabled())
        return server, connected_client

    def test_condition_schema_is_exposed(self, server):
        server, _ = server
        tools = {t.name: t for t in asyncio.run(server.list_tools())}
        schema = json.dumps(tools["add_filter"].inputSchema)
        assert '"field"' in schema
        assert '"contains"' in schema and '"is"' in schema
        assert '"domain"' in schema

    def test_json_conditions_are_validated(self, server):
        server, client = server
        asyncio.run(server.call_tool("add_filter", {
            "name": "VRSPAM",
            "conditions": [{"field": "X-VRSPAM-STATE", "value": "spam", "comparison": "is"}],
            "folder": "Junk",
        }))
        assert _written(client)[1]["filterTests"][0]["headerTest"][0]["stringComparison"] == "is"

    def test_invalid_comparison_is_rejected_before_writing(self, server):
        server, client = server
        with pytest.raises(ToolError, match="comparison"):
            asyncio.run(server.call_tool("add_filter_condition", {
                "name": "News", "condition": {"field": "sender", "value": "a", "comparison": "matches"},
            }))
        client.modify_filter_rules.assert_not_called()


class TestGetMessageHeaders:
    def test_normalizes_names_and_lists(self, connected_client):
        connected_client.request = MagicMock(return_value={"m": [{"id": "1", "_attrs": {
            "From": "Bob <bob@a.com>", "Received": ["r1", "r2"],
        }}]})
        headers = connected_client.get_message_headers("1", ["From", "Received", "List-Id"])
        assert headers == {"from": ["Bob <bob@a.com>"], "received": ["r1", "r2"]}
        params = connected_client.request.call_args[0][2]
        assert params == {"m": {"id": "1", "header": [{"n": "From"}, {"n": "Received"}, {"n": "List-Id"}]}}

    def test_no_attrs(self, connected_client):
        connected_client.request = MagicMock(return_value={"m": {"id": "1"}})
        assert connected_client.get_message_headers("1", ["From"]) == {}


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
