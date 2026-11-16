"""MCP tools for Zimbra calendar management."""

from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

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
                    "duration_minutes": (inst.get("dur") or appt.get("dur") or 0) // 60000,
                    "all_day": _is_true(appt.get("allDay")),
                    "is_recurring": _is_true(appt.get("recur")),
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
            "description": _text(comp.get("desc")),
            "start": start_info.get("d"),
            "end": end_info.get("d"),
            "timezone": start_info.get("tz"),
            "all_day": _is_true(comp.get("allDay")),
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
        private: bool = False,
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
            private: Private event, its details hidden from people who share the calendar (default: False)

        Returns:
            Information about the created event
        """
        start_dt = _parse_input_datetime(start_datetime, all_day)
        end_dt = _parse_input_datetime(end_datetime, all_day)

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
            private=private,
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
            "private": private,
        }

    @mcp.tool()
    def update_event(
        event_id: str,
        subject: str | None = None,
        start_datetime: str | None = None,
        end_datetime: str | None = None,
        location: str | None = None,
        description: str | None = None,
        private: bool | None = None,
    ) -> dict[str, Any]:
        """Modify an event you organize. Only the given fields change.

        A recurring event is modified as a whole series. Attendees are not notified.

        Args:
            event_id: Event ID (obtained via get_calendar_events)
            subject: New title (optional)
            start_datetime: New start in "YYYY-MM-DD HH:MM" or "YYYY-MM-DD" format for all-day events.
                Without end_datetime, the end moves to keep the duration (optional)
            end_datetime: New end, same format (optional)
            location: New location (optional)
            description: New description, replacing the current one (optional)
            private: True to make the event private, False to make it public (optional)

        Returns:
            The modified event
        """
        changes = (subject, start_datetime, end_datetime, location, description, private)
        if all(value is None for value in changes):
            return {"success": False, "error": "Nothing to update"}

        appt = _first(client.get_appointment(event_id).get("appt"))
        inv = _series_invite(appt)
        if inv is None:
            return {"success": False, "error": f"Event {event_id} not found"}

        comp = _first(inv.get("comp"))
        if not _is_true(comp.get("isOrg")):
            return {"success": False, "error": "Only events you organize can be modified"}

        all_day = _is_true(comp.get("allDay"))
        old_start, old_end = _first(comp.get("s")), _first(comp.get("e"))
        zone = None
        if (start_datetime or end_datetime) and _has_utc_time(old_start, old_end):
            zone = _zone(client.get_timezone())
        try:
            start, end = _reschedule(old_start, old_end, start_datetime, end_datetime, all_day, zone)
        except ValueError as e:
            return {"success": False, "error": str(e)}

        new_comp = {key: comp[key] for key in _WRITABLE_COMP_KEYS if key in comp}
        new_comp["s"] = start
        new_comp["e"] = end
        if subject is not None:
            new_comp["name"] = subject
        if location is not None:
            new_comp["loc"] = location
        if private is not None:
            new_comp["class"] = "PRI" if private else "PUB"

        text, html = _text(comp.get("desc")), _text(comp.get("descHtml")) or None
        if description is not None:
            text, html = description, None

        new_inv: dict[str, Any] = {"comp": new_comp}
        if inv.get("tz"):
            new_inv["tz"] = inv["tz"]

        client.modify_appointment(f"{appt['id']}-{inv['id']}", new_inv, text, html)

        result = {
            "success": True,
            "event_id": appt["id"],
            "subject": new_comp.get("name", ""),
            "start": start["d"],
            "end": end["d"],
            "location": new_comp.get("loc", ""),
            "private": new_comp.get("class") == "PRI",
        }
        if comp.get("at"):
            result["warning"] = "Attendees were not notified of the change"
        return result

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


_WRITABLE_COMP_KEYS = (
    "name", "loc", "allDay", "alarm", "recur", "at", "or", "class",
    "status", "fb", "fba", "transp", "priority", "url",
)


def _first(value: Any) -> dict[str, Any]:
    """Return a Zimbra element given alone or as the first item of a list."""
    if isinstance(value, list):
        return value[0] if value else {}
    return value or {}


def _series_invite(appt: dict[str, Any]) -> dict[str, Any] | None:
    """Return the invite of an event that is not an exception of a recurring series."""
    invites = appt.get("inv") or []
    if not isinstance(invites, list):
        invites = [invites]
    for inv in invites:
        if not _is_true(_first(inv.get("comp")).get("ex")):
            return inv
    return None


def _parse_input_datetime(value: str, all_day: bool) -> datetime:
    """Parse a "YYYY-MM-DD HH:MM" (or "YYYY-MM-DDTHH:MM") date, or "YYYY-MM-DD" for all-day events."""
    if all_day:
        return datetime.strptime(value[:10], "%Y-%m-%d")
    try:
        return datetime.strptime(value, "%Y-%m-%d %H:%M")
    except ValueError:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M")


def _parse_zimbra_date(value: str) -> datetime:
    """Parse a Zimbra "YYYYMMDD'T'HHMMSS" or "YYYYMMDD" date, ignoring a UTC suffix."""
    value = value.rstrip("Z")
    if len(value) == 8:
        return datetime.strptime(value, "%Y%m%d")
    return datetime.strptime(value, "%Y%m%dT%H%M%S")


def _has_utc_time(*elements: dict[str, Any]) -> bool:
    """Tell whether one of the date elements is in UTC ("...Z")."""
    return any(str(element.get("d", "")).endswith("Z") for element in elements)


def _zone(name: str | None) -> ZoneInfo | None:
    """Return the time zone named by an IANA ID, or None when it is unknown."""
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError, TypeError):
        return None


def _wall_time(value: str, zone: ZoneInfo | None) -> datetime:
    """Parse a Zimbra date, converting a UTC one to the wall time of the given zone."""
    parsed = _parse_zimbra_date(value)
    if not value.endswith("Z") or zone is None:
        return parsed
    return parsed.replace(tzinfo=timezone.utc).astimezone(zone).replace(tzinfo=None)


def _reschedule(
    start: dict[str, Any],
    end: dict[str, Any],
    start_input: str | None,
    end_input: str | None,
    all_day: bool,
    zone: ZoneInfo | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Return the new start and end elements, keeping the time zone and, without a new end, the duration.

    Raises:
        ValueError: A date cannot be parsed, or the event would end before it starts
    """
    end = end or start
    fmt = "%Y%m%d" if all_day else "%Y%m%dT%H%M%S"

    def element(original: dict[str, Any], when: datetime | None) -> dict[str, Any]:
        if when is None:
            return {key: original[key] for key in ("d", "tz") if key in original}
        new = {"d": when.strftime(fmt)}
        if "tz" in original:
            new["tz"] = original["tz"]
        return new

    if start_input is None and end_input is None:
        return element(start, None), element(end, None)

    old_start = _wall_time(start["d"], zone)
    old_end = _wall_time(end["d"], zone)
    new_start = _parse_input_datetime(start_input, all_day) if start_input else old_start
    if end_input:
        new_end = _parse_input_datetime(end_input, all_day)
    elif start_input:
        new_end = new_start + (old_end - old_start)
    else:
        new_end = old_end
    if new_end < new_start:
        raise ValueError("The event would end before it starts")
    return element(start, new_start if start_input else None), element(end, new_end)


def _text(value: Any) -> str:
    """Return the text of a Zimbra element given as a string, a dict or a list of dicts."""
    if isinstance(value, list):
        value = value[0] if value else None
    if isinstance(value, dict):
        value = value.get("_content")
    return value or ""


def _is_true(value: Any) -> bool:
    """Read a Zimbra boolean attribute, returned as a bool or as "1"/"0"."""
    return value is True or value in ("1", "true", "TRUE")


def _ms_to_datetime(ms: int | None) -> str | None:
    """Convert a timestamp in milliseconds to ISO datetime."""
    if ms is None:
        return None
    return datetime.fromtimestamp(ms / 1000).strftime("%Y-%m-%d %H:%M")


_TRIGGER_UNIT_MINUTES = {"w": 7 * 24 * 60, "d": 24 * 60, "h": 60, "m": 1}


def _trigger_minutes(rel: dict[str, Any]) -> int:
    """Return the length of a relative alarm trigger in minutes, whatever its units."""
    seconds = abs(int(rel.get("s", 0)))
    return sum(abs(int(rel.get(unit, 0))) * size for unit, size in _TRIGGER_UNIT_MINUTES.items()) + seconds // 60


def _extract_alarm(alarms: list | dict) -> dict | None:
    """Extract alarm information."""
    if not alarms:
        return None
    if not isinstance(alarms, list):
        alarms = [alarms]
    if not alarms:
        return None

    alarm = alarms[0]
    rel = _first(_first(alarm.get("trigger")).get("rel"))

    return {
        "action": alarm.get("action"),
        "minutes_before": _trigger_minutes(rel) if rel else None,
    }
