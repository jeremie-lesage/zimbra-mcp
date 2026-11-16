"""Tests for calendar tools."""

from datetime import datetime
from unittest.mock import MagicMock
from zoneinfo import ZoneInfo

import pytest

from tests.conftest import capture_tools
from zimbra_mcp.tools.calendar import (
    _extract_alarm,
    _is_true,
    _ms_to_datetime,
    _parse_input_datetime,
    _parse_zimbra_date,
    _text,
    _wall_time,
    _zone,
    register_calendar_tools,
)


@pytest.mark.parametrize(
    ("value", "expected"),
    [("a", "a"), ({"_content": "a"}, "a"), ([{"_content": "a"}], "a"), ([], ""), ([{}], ""), (None, "")],
)
def test_text(value, expected):
    assert _text(value) == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [(True, True), ("1", True), (False, False), ("0", False), (None, False)],
)
def test_is_true(value, expected):
    assert _is_true(value) is expected


class TestMsToDatetime:
    def test_valid(self):
        # 2024-01-15 10:30 UTC = 1705312200000 ms
        result = _ms_to_datetime(1705312200000)
        assert result is not None
        assert "2024-01-15" in result

    def test_none(self):
        assert _ms_to_datetime(None) is None


class TestExtractAlarm:
    def test_with_alarm(self):
        alarms = [{"action": "DISPLAY", "trigger": {"rel": {"m": -15}}}]
        result = _extract_alarm(alarms)
        assert result is not None
        assert result["action"] == "DISPLAY"
        assert result["minutes_before"] == 15

    def test_lists_as_returned_by_zimbra(self):
        alarms = [{"action": "DISPLAY", "trigger": [{"rel": [{"neg": True, "m": 15, "related": "START"}]}]}]
        assert _extract_alarm(alarms) == {"action": "DISPLAY", "minutes_before": 15}

    @pytest.mark.parametrize(
        ("rel", "minutes"),
        [
            ({"neg": True, "h": 1}, 60),
            ({"neg": True, "d": 1}, 1440),
            ({"neg": True, "w": 1}, 10080),
            ({"neg": True, "h": 1, "m": 30}, 90),
            ({"neg": True, "s": 120}, 2),
            ({"neg": True, "m": "5"}, 5),
        ],
    )
    def test_units(self, rel, minutes):
        alarms = [{"action": "DISPLAY", "trigger": [{"rel": [rel]}]}]
        assert _extract_alarm(alarms)["minutes_before"] == minutes

    def test_absolute_trigger(self):
        alarms = [{"action": "DISPLAY", "trigger": [{"abs": [{"d": "20300115T090000Z"}]}]}]
        assert _extract_alarm(alarms)["minutes_before"] is None

    def test_empty(self):
        assert _extract_alarm([]) is None
        assert _extract_alarm({}) is None

    def test_single_dict(self):
        alarm = {"action": "DISPLAY", "trigger": {"rel": {"m": -30}}}
        result = _extract_alarm(alarm)
        assert result["minutes_before"] == 30


@pytest.fixture
def cal_tools(connected_client):
    tools = capture_tools(register_calendar_tools, connected_client)
    return tools, connected_client


class TestGetCalendarEvents:
    def test_get_events(self, cal_tools):
        tools, client = cal_tools
        client.search_calendar = MagicMock(return_value={
            "appt": [
                {
                    "id": "500",
                    "uid": "uid-500",
                    "name": "Team Meeting",
                    "loc": "Room 1",
                    "inst": [{"s": 1705312200000, "dur": 3600000}],
                    "or": {"a": "boss@test.com"},
                    "fr": "Agenda...",
                }
            ]
        })

        result = tools["get_calendar_events"](start_date="2024-01-15", days=1)
        assert result["count"] == 1
        assert result["events"][0]["name"] == "Team Meeting"
        assert result["events"][0]["duration_minutes"] == 60

    def test_get_events_empty(self, cal_tools):
        tools, client = cal_tools
        client.search_calendar = MagicMock(return_value={})

        result = tools["get_calendar_events"](start_date="2024-01-15")
        assert result["count"] == 0

    def test_recurring_instances(self, cal_tools):
        tools, client = cal_tools
        client.search_calendar = MagicMock(return_value={
            "appt": [{
                "id": "600",
                "name": "Daily",
                "dur": 1800000,
                "recur": True,
                "inst": [
                    {"s": 1705312200000, "ridZ": "20240115T103000Z"},
                    {"s": 1705398600000, "dur": 2700000, "ridZ": "20240116T103000Z", "ex": True},
                ],
            }]
        })

        result = tools["get_calendar_events"](start_date="2024-01-15", days=2)
        assert result["count"] == 2
        assert all(e["is_recurring"] for e in result["events"])
        assert [e["duration_minutes"] for e in result["events"]] == [30, 45]

    def test_single_event_with_rid(self, cal_tools):
        tools, client = cal_tools
        client.search_calendar = MagicMock(return_value={
            "appt": [{
                "id": "601",
                "name": "One-off",
                "dur": 10800000,
                "allDay": False,
                "inst": [{"s": 1705312200000, "ridZ": "20240115T103000Z"}],
            }]
        })

        event = tools["get_calendar_events"](start_date="2024-01-15", days=1)["events"][0]
        assert event["is_recurring"] is False
        assert event["duration_minutes"] == 180
        assert event["all_day"] is False

    def test_all_day_boolean(self, cal_tools):
        tools, client = cal_tools
        client.search_calendar = MagicMock(return_value={
            "appt": [{
                "id": "602",
                "name": "Holiday",
                "dur": 86400000,
                "allDay": True,
                "recur": True,
                "inst": [{"s": 1705276800000, "ridZ": "20240115"}],
            }]
        })

        event = tools["get_calendar_events"](start_date="2024-01-15", days=1)["events"][0]
        assert event["all_day"] is True
        assert event["duration_minutes"] == 1440


class TestGetEventDetails:
    def test_get_details(self, cal_tools):
        tools, client = cal_tools
        client.get_appointment = MagicMock(return_value={
            "appt": {
                "id": "500",
                "inv": [{
                    "comp": [{
                        "uid": "uid-500",
                        "name": "Meeting",
                        "loc": "Room 1",
                        "desc": [{"_content": "Discuss project"}],
                        "s": [{"d": "20240115T103000"}],
                        "e": [{"d": "20240115T113000"}],
                        "or": {"a": "boss@test.com", "d": "Boss"},
                        "at": [
                            {"a": "alice@test.com", "d": "Alice", "role": "REQ", "ptst": "AC"},
                        ],
                        "alarm": [{"action": "DISPLAY", "trigger": {"rel": {"m": -10}}}],
                    }],
                }],
            }
        })

        result = tools["get_event_details"]("500")
        assert result["name"] == "Meeting"
        assert result["description"] == "Discuss project"
        assert len(result["attendees"]) == 1
        assert result["attendees"][0]["email"] == "alice@test.com"
        assert result["alarm"]["minutes_before"] == 10


class TestCreateEvent:
    def test_create_event(self, cal_tools):
        tools, client = cal_tools
        client.create_appointment = MagicMock(return_value={
            "calItemId": "700",
            "invId": "700-1",
        })

        result = tools["create_event"](
            subject="Lunch",
            start_datetime="2024-01-15 12:00",
            end_datetime="2024-01-15 13:00",
            location="Cafeteria",
        )
        assert result["success"] is True
        assert result["event_id"] == "700"
        assert result["location"] == "Cafeteria"

    def test_create_all_day_event(self, cal_tools):
        tools, client = cal_tools
        client.create_appointment = MagicMock(return_value={
            "calItemId": "701",
        })

        result = tools["create_event"](
            subject="Holiday",
            start_datetime="2024-01-15",
            end_datetime="2024-01-16",
            all_day=True,
        )
        assert result["success"] is True
        assert result["all_day"] is True

    def test_create_private_event(self, cal_tools):
        tools, client = cal_tools
        client.create_appointment = MagicMock(return_value={"calItemId": "702"})

        result = tools["create_event"](
            subject="Doctor",
            start_datetime="2024-01-15 12:00",
            end_datetime="2024-01-15 13:00",
            private=True,
        )
        assert result["private"] is True
        assert client.create_appointment.call_args.kwargs["private"] is True


def _appt(comp_overrides=None, extra_invites=()):
    comp = {
        "isOrg": True,
        "uid": "uid-800",
        "calItemId": "800",
        "name": "Weekly",
        "loc": "Room 1",
        "class": "PUB",
        "s": [{"d": "20300115T100000", "tz": "Europe/Paris", "u": 1894698000000}],
        "e": [{"d": "20300115T113000", "tz": "Europe/Paris", "u": 1894703400000}],
        "alarm": [{"action": "DISPLAY", "trigger": [{"rel": [{"neg": True, "m": 15}]}]}],
        "recur": [{"add": [{"rule": [{"freq": "WEE"}]}]}],
        "desc": [{"_content": "plain"}],
        "descHtml": [{"_content": "<p>html</p>"}],
    }
    comp.update(comp_overrides or {})
    tz = [{"id": "Europe/Paris", "stdoff": 60}]
    return {"appt": {"id": "800", "inv": [*extra_invites, {"id": 799, "tz": tz, "comp": [comp]}]}}


class TestUpdateEvent:
    def _sent(self, client):
        args = client.modify_appointment.call_args.args
        return args[0], args[1], args[2], args[3]

    def test_private_only_keeps_the_rest(self, cal_tools):
        tools, client = cal_tools
        client.get_appointment = MagicMock(return_value=_appt())
        client.modify_appointment = MagicMock(return_value={})

        result = tools["update_event"]("800", private=True)

        invite_id, inv, text, html = self._sent(client)
        comp = inv["comp"]
        assert result["success"] is True
        assert result["private"] is True
        assert invite_id == "800-799"
        assert comp["class"] == "PRI"
        assert comp["name"] == "Weekly"
        assert comp["recur"] == [{"add": [{"rule": [{"freq": "WEE"}]}]}]
        assert comp["alarm"][0]["action"] == "DISPLAY"
        assert comp["s"] == {"d": "20300115T100000", "tz": "Europe/Paris"}
        assert comp["e"] == {"d": "20300115T113000", "tz": "Europe/Paris"}
        assert not {"isOrg", "uid", "calItemId", "desc", "descHtml"} & comp.keys()
        assert inv["tz"] == [{"id": "Europe/Paris", "stdoff": 60}]
        assert (text, html) == ("plain", "<p>html</p>")
        assert "warning" not in result

    def test_make_public(self, cal_tools):
        tools, client = cal_tools
        client.get_appointment = MagicMock(return_value=_appt({"class": "PRI"}))
        client.modify_appointment = MagicMock(return_value={})

        assert tools["update_event"]("800", private=False)["private"] is False
        assert self._sent(client)[1]["comp"]["class"] == "PUB"

    def test_new_start_keeps_duration(self, cal_tools):
        tools, client = cal_tools
        client.get_appointment = MagicMock(return_value=_appt())
        client.modify_appointment = MagicMock(return_value={})

        result = tools["update_event"]("800", start_datetime="2030-01-16 14:00")

        comp = self._sent(client)[1]["comp"]
        assert comp["s"] == {"d": "20300116T140000", "tz": "Europe/Paris"}
        assert comp["e"] == {"d": "20300116T153000", "tz": "Europe/Paris"}
        assert (result["start"], result["end"]) == ("20300116T140000", "20300116T153000")

    def test_new_end_only(self, cal_tools):
        tools, client = cal_tools
        client.get_appointment = MagicMock(return_value=_appt())
        client.modify_appointment = MagicMock(return_value={})

        tools["update_event"]("800", end_datetime="2030-01-15T12:00")

        comp = self._sent(client)[1]["comp"]
        assert comp["s"]["d"] == "20300115T100000"
        assert comp["e"]["d"] == "20300115T120000"

    def test_all_day(self, cal_tools):
        tools, client = cal_tools
        client.get_appointment = MagicMock(return_value=_appt({
            "allDay": True, "s": [{"d": "20300115"}], "e": [{"d": "20300115"}],
        }))
        client.modify_appointment = MagicMock(return_value={})

        tools["update_event"]("800", start_datetime="2030-01-20")

        comp = self._sent(client)[1]["comp"]
        assert comp["s"] == {"d": "20300120"}
        assert comp["e"] == {"d": "20300120"}
        assert comp["allDay"] is True

    def test_end_before_start(self, cal_tools):
        tools, client = cal_tools
        client.get_appointment = MagicMock(return_value=_appt())
        client.modify_appointment = MagicMock()

        result = tools["update_event"]("800", end_datetime="2030-01-15 09:00")

        assert result["success"] is False
        client.modify_appointment.assert_not_called()

    def test_new_description_drops_html(self, cal_tools):
        tools, client = cal_tools
        client.get_appointment = MagicMock(return_value=_appt())
        client.modify_appointment = MagicMock(return_value={})

        tools["update_event"]("800", description="new", subject="Renamed", location="")

        _, inv, text, html = self._sent(client)
        assert (text, html) == ("new", None)
        assert inv["comp"]["name"] == "Renamed"
        assert inv["comp"]["loc"] == ""

    def test_nothing_to_update(self, cal_tools):
        tools, client = cal_tools
        client.get_appointment = MagicMock()

        result = tools["update_event"]("800")

        assert result["success"] is False
        client.get_appointment.assert_not_called()

    def test_not_organizer(self, cal_tools):
        tools, client = cal_tools
        client.get_appointment = MagicMock(return_value=_appt({"isOrg": False}))
        client.modify_appointment = MagicMock()

        result = tools["update_event"]("800", private=True)

        assert result["success"] is False
        client.modify_appointment.assert_not_called()

    def test_skips_exceptions(self, cal_tools):
        tools, client = cal_tools
        exception = {"id": 801, "comp": [{"ex": True, "isOrg": True, "name": "Moved once"}]}
        client.get_appointment = MagicMock(return_value=_appt(extra_invites=[exception]))
        client.modify_appointment = MagicMock(return_value={})

        tools["update_event"]("800", private=True)

        invite_id, inv, _, _ = self._sent(client)
        assert invite_id == "800-799"
        assert inv["comp"]["name"] == "Weekly"

    def test_only_exceptions(self, cal_tools):
        tools, client = cal_tools
        client.get_appointment = MagicMock(return_value={"appt": {"id": "800", "inv": {"id": 1, "comp": {"ex": True}}}})
        client.modify_appointment = MagicMock()

        assert tools["update_event"]("800", private=True)["success"] is False
        client.modify_appointment.assert_not_called()

    def test_utc_times_read_in_account_zone(self, cal_tools):
        tools, client = cal_tools
        client.get_appointment = MagicMock(return_value=_appt({
            "s": [{"d": "20300715T080000Z"}], "e": [{"d": "20300715T083000Z"}],
        }))
        client.get_timezone = MagicMock(return_value="Europe/Brussels")
        client.modify_appointment = MagicMock(return_value={})

        tools["update_event"]("800", start_datetime="2030-07-15 15:00")

        comp = self._sent(client)[1]["comp"]
        assert comp["s"] == {"d": "20300715T150000"}
        assert comp["e"] == {"d": "20300715T153000"}

    def test_mixed_utc_and_local_end_check(self, cal_tools):
        tools, client = cal_tools
        client.get_appointment = MagicMock(return_value=_appt({
            "s": [{"d": "20300715T080000Z"}], "e": [{"d": "20300715T090000Z"}],
        }))
        client.get_timezone = MagicMock(return_value="Europe/Brussels")
        client.modify_appointment = MagicMock(return_value={})

        assert tools["update_event"]("800", end_datetime="2030-07-15 09:30")["success"] is False
        tools["update_event"]("800", end_datetime="2030-07-15 10:30")
        comp = self._sent(client)[1]["comp"]
        assert comp["s"] == {"d": "20300715T080000Z"}
        assert comp["e"] == {"d": "20300715T103000"}

    def test_account_zone_not_fetched_without_utc(self, cal_tools):
        tools, client = cal_tools
        client.get_appointment = MagicMock(return_value=_appt())
        client.get_timezone = MagicMock()
        client.modify_appointment = MagicMock(return_value={})

        tools["update_event"]("800", start_datetime="2030-01-16 14:00")

        client.get_timezone.assert_not_called()

    def test_invalid_date(self, cal_tools):
        tools, client = cal_tools
        client.get_appointment = MagicMock(return_value=_appt())
        client.modify_appointment = MagicMock()

        assert tools["update_event"]("800", start_datetime="tomorrow")["success"] is False
        client.modify_appointment.assert_not_called()

    def test_attendees_warning(self, cal_tools):
        tools, client = cal_tools
        client.get_appointment = MagicMock(return_value=_appt({"at": [{"a": "alice@test.com"}]}))
        client.modify_appointment = MagicMock(return_value={})

        result = tools["update_event"]("800", private=True)

        assert result["warning"] == "Attendees were not notified of the change"
        assert self._sent(client)[1]["comp"]["at"] == [{"a": "alice@test.com"}]


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("20300115T100000", datetime(2030, 1, 15, 10, 0)),
        ("20300115T100000Z", datetime(2030, 1, 15, 10, 0)),
        ("20300115", datetime(2030, 1, 15)),
    ],
)
def test_parse_zimbra_date(value, expected):
    assert _parse_zimbra_date(value) == expected


@pytest.mark.parametrize(
    ("name", "expected"),
    [("Europe/Paris", ZoneInfo("Europe/Paris")), ("Not/AZone", None), ("", None), (None, None)],
)
def test_zone(name, expected):
    assert _zone(name) == expected


def test_wall_time():
    zone = ZoneInfo("Europe/Brussels")
    assert _wall_time("20300715T080000Z", zone) == datetime(2030, 7, 15, 10, 0)
    assert _wall_time("20300115T080000Z", zone) == datetime(2030, 1, 15, 9, 0)
    assert _wall_time("20300715T080000", zone) == datetime(2030, 7, 15, 8, 0)
    assert _wall_time("20300715T080000Z", None) == datetime(2030, 7, 15, 8, 0)


def test_parse_input_datetime_rejects_garbage():
    with pytest.raises(ValueError):
        _parse_input_datetime("tomorrow", all_day=False)


class TestGetFreeBusy:
    def test_get_free_busy(self, cal_tools):
        tools, client = cal_tools
        client.get_free_busy = MagicMock(return_value={
            "usr": [{
                "id": "alice@test.com",
                "b": [{"s": 1705312200000, "e": 1705315800000}],
                "f": [{"s": 1705315800000, "e": 1705319400000}],
                "t": [{"s": 1705319400000, "e": 1705323000000}],
            }]
        })

        result = tools["get_free_busy"]("alice@test.com", start_date="2024-01-15")
        assert len(result["busy_slots"]) == 2  # 1 busy + 1 tentative
        assert len(result["free_slots"]) == 1
        assert result["email"] == "alice@test.com"
