"""Tests for calendar tools."""

from unittest.mock import MagicMock

import pytest

from tests.conftest import capture_tools
from zimbra_mcp.tools.calendar import (
    _extract_alarm,
    _ms_to_datetime,
    register_calendar_tools,
)


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
                "inst": [
                    {"s": 1705312200000, "dur": 1800000, "ridZ": "20240115T103000Z"},
                    {"s": 1705398600000, "dur": 1800000, "ridZ": "20240116T103000Z"},
                ],
            }]
        })

        result = tools["get_calendar_events"](start_date="2024-01-15", days=2)
        assert result["count"] == 2
        assert all(e["is_recurring"] for e in result["events"])


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
                        "desc": "Discuss project",
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
