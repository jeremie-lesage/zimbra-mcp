"""MCP tools for Zimbra calendar management."""

from datetime import datetime, timedelta
from typing import Any

from mcp.server.fastmcp import FastMCP

from zimbra_mcp.client import ZimbraClient


def register_calendar_tools(mcp: FastMCP, client: ZimbraClient) -> None:
    """Register calendar management tools.

    Args:
        mcp: FastMCP instance
        client: Zimbra client
    """

    @mcp.tool()
    def get_calendar_events(
        start_date: str | None = None,
        end_date: str | None = None,
        days: int = 7,
    ) -> dict[str, Any]:
        """Retrieve calendar events over a period.

        Args:
            start_date: Start date in YYYY-MM-DD format (default: today)
            end_date: End date in YYYY-MM-DD format (optional)
            days: Number of days from start_date if end_date is not specified (default: 7)

        Returns:
            List of events with their details
        """
        if start_date:
            start_dt = datetime.strptime(start_date, "%Y-%m-%d")
        else:
            start_dt = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)

        if end_date:
            end_dt = datetime.strptime(end_date, "%Y-%m-%d")
            end_dt = end_dt.replace(hour=23, minute=59, second=59)
        else:
            end_dt = start_dt + timedelta(days=days)

        start_ms = int(start_dt.timestamp() * 1000)
        end_ms = int(end_dt.timestamp() * 1000)

        result = client.search_calendar(start_ms, end_ms)

        appointments = result.get("appt", [])
        if not isinstance(appointments, list):
            appointments = [appointments] if appointments else []

        events = []
        for appt in appointments:
            instances = appt.get("inst", [])
            if not isinstance(instances, list):
                instances = [instances] if instances else []

            for inst in instances:
                event_info = {
                    "id": appt.get("id"),
                    "uid": appt.get("uid"),
                    "name": appt.get("name", "(no title)"),
                    "location": appt.get("loc", ""),
                    "start": _ms_to_datetime(inst.get("s")),
                    "start_ms": inst.get("s"),
                    "duration_minutes": (inst.get("dur", 0) or 0) // 60000,
                    "all_day": appt.get("allDay", "0") == "1",
                    "is_recurring": inst.get("ridZ") is not None,
                    "organizer": appt.get("or", {}).get("a"),
                    "status": appt.get("status"),
                    "fragment": appt.get("fr", ""),
                }
                events.append(event_info)

        events.sort(key=lambda e: e.get("start_ms", 0))

        return {
            "events": events,
            "period": {
                "start": start_dt.strftime("%Y-%m-%d"),
                "end": end_dt.strftime("%Y-%m-%d"),
            },
            "count": len(events),
        }

    @mcp.tool()
    def get_event_details(event_id: str) -> dict[str, Any]:
        """Retrieve full details of an event.

        Args:
            event_id: Event ID (obtained via get_calendar_events)

        Returns:
            Full event details including description and attendees
        """
        result = client.get_appointment(event_id)

        appt = result.get("appt", {})
        if isinstance(appt, list):
            appt = appt[0] if appt else {}

        inv = appt.get("inv", [{}])
        if isinstance(inv, list):
            inv = inv[0] if inv else {}

        comp = inv.get("comp", [{}])
        if isinstance(comp, list):
            comp = comp[0] if comp else {}

        attendees = []
        at_list = comp.get("at", [])
        if not isinstance(at_list, list):
            at_list = [at_list] if at_list else []
        for at in at_list:
            attendees.append({
                "email": at.get("a"),
                "name": at.get("d"),
                "role": at.get("role"),
                "status": at.get("ptst"),
            })

        start_info = comp.get("s", [{}])
        if isinstance(start_info, list):
            start_info = start_info[0] if start_info else {}

        end_info = comp.get("e", [{}])
        if isinstance(end_info, list):
            end_info = end_info[0] if end_info else {}

        return {
            "id": appt.get("id"),
            "uid": comp.get("uid"),
            "name": comp.get("name", "(no title)"),
            "location": comp.get("loc", ""),
            "description": comp.get("desc", ""),
            "start": start_info.get("d"),
            "end": end_info.get("d"),
            "timezone": start_info.get("tz"),
            "all_day": comp.get("allDay") == "1",
            "status": comp.get("status"),
            "class": comp.get("class", "PUB"),
            "organizer": {
                "email": comp.get("or", {}).get("a"),
                "name": comp.get("or", {}).get("d"),
            },
            "attendees": attendees,
            "recurrence": comp.get("recur"),
            "alarm": _extract_alarm(comp.get("alarm", [])),
        }

    @mcp.tool()
    def create_event(
        subject: str,
        start_datetime: str,
        end_datetime: str,
        location: str | None = None,
        description: str | None = None,
        attendees: list[str] | None = None,
        all_day: bool = False,
    ) -> dict[str, Any]:
        """Create a calendar event.

        Args:
            subject: Event title
            start_datetime: Start date/time in "YYYY-MM-DD HH:MM" or "YYYY-MM-DD" format for all-day events
            end_datetime: End date/time in "YYYY-MM-DD HH:MM" or "YYYY-MM-DD" format for all-day events
            location: Event location (optional)
            description: Event description (optional)
            attendees: List of attendee emails (optional)
            all_day: All-day event (default: False)

        Returns:
            Information about the created event
        """
        if all_day:
            start_dt = datetime.strptime(start_datetime[:10], "%Y-%m-%d")
            end_dt = datetime.strptime(end_datetime[:10], "%Y-%m-%d")
        else:
            try:
                start_dt = datetime.strptime(start_datetime, "%Y-%m-%d %H:%M")
                end_dt = datetime.strptime(end_datetime, "%Y-%m-%d %H:%M")
            except ValueError:
                start_dt = datetime.strptime(start_datetime, "%Y-%m-%dT%H:%M")
                end_dt = datetime.strptime(end_datetime, "%Y-%m-%dT%H:%M")

        start_ms = int(start_dt.timestamp() * 1000)
        end_ms = int(end_dt.timestamp() * 1000)

        result = client.create_appointment(
            subject=subject,
            start_time=start_ms,
            end_time=end_ms,
            location=location,
            description=description,
            attendees=attendees,
            all_day=all_day,
        )

        return {
            "success": True,
            "event_id": result.get("calItemId") or result.get("apptId"),
            "invite_id": result.get("invId"),
            "subject": subject,
            "start": start_datetime,
            "end": end_datetime,
            "location": location,
            "attendees": attendees,
            "all_day": all_day,
        }

    @mcp.tool()
    def get_free_busy(
        email: str,
        start_date: str | None = None,
        end_date: str | None = None,
        days: int = 7,
    ) -> dict[str, Any]:
        """Retrieve user availability.

        Args:
            email: User email address
            start_date: Start date in YYYY-MM-DD format (default: today)
            end_date: End date in YYYY-MM-DD format (optional)
            days: Number of days if end_date is not specified (default: 7)

        Returns:
            User's busy and free slots
        """
        if start_date:
            start_dt = datetime.strptime(start_date, "%Y-%m-%d")
        else:
            start_dt = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)

        if end_date:
            end_dt = datetime.strptime(end_date, "%Y-%m-%d")
            end_dt = end_dt.replace(hour=23, minute=59, second=59)
        else:
            end_dt = start_dt + timedelta(days=days)

        start_ms = int(start_dt.timestamp() * 1000)
        end_ms = int(end_dt.timestamp() * 1000)

        result = client.get_free_busy(email, start_ms, end_ms)

        users = result.get("usr", [])
        if not isinstance(users, list):
            users = [users] if users else []

        busy_slots = []
        free_slots = []

        for user in users:
            if user.get("id") == email:
                # Busy slots
                busy = user.get("b", [])
                if not isinstance(busy, list):
                    busy = [busy] if busy else []
                for slot in busy:
                    busy_slots.append({
                        "start": _ms_to_datetime(slot.get("s")),
                        "end": _ms_to_datetime(slot.get("e")),
                        "type": "busy",
                    })

                # Tentative slots
                tentative = user.get("t", [])
                if not isinstance(tentative, list):
                    tentative = [tentative] if tentative else []
                for slot in tentative:
                    busy_slots.append({
                        "start": _ms_to_datetime(slot.get("s")),
                        "end": _ms_to_datetime(slot.get("e")),
                        "type": "tentative",
                    })

                # Free slots
                free = user.get("f", [])
                if not isinstance(free, list):
                    free = [free] if free else []
                for slot in free:
                    free_slots.append({
                        "start": _ms_to_datetime(slot.get("s")),
                        "end": _ms_to_datetime(slot.get("e")),
                    })

        return {
            "email": email,
            "period": {
                "start": start_dt.strftime("%Y-%m-%d"),
                "end": end_dt.strftime("%Y-%m-%d"),
            },
            "busy_slots": sorted(busy_slots, key=lambda s: s.get("start", "")),
            "free_slots": sorted(free_slots, key=lambda s: s.get("start", "")),
        }


def _ms_to_datetime(ms: int | None) -> str | None:
    """Convert a timestamp in milliseconds to ISO datetime."""
    if ms is None:
        return None
    return datetime.fromtimestamp(ms / 1000).strftime("%Y-%m-%d %H:%M")


def _extract_alarm(alarms: list | dict) -> dict | None:
    """Extract alarm information."""
    if not alarms:
        return None
    if not isinstance(alarms, list):
        alarms = [alarms]
    if not alarms:
        return None

    alarm = alarms[0]
    trigger = alarm.get("trigger", {})
    rel = trigger.get("rel", {})

    return {
        "action": alarm.get("action"),
        "minutes_before": abs(rel.get("m", 0)) if rel else None,
    }
