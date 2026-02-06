"""Zimbra SOAP Client."""

from typing import Any

from pythonzimbra.communication import Communication
from pythonzimbra.tools import auth

from zimbra_mcp.config import ZimbraConfig
from zimbra_mcp.errors import (
    ZimbraAuthError,
    ZimbraConnectionError,
    ZimbraNotFoundError,
    ZimbraOperationError,
)


class ZimbraClient:
    """Client for the Zimbra SOAP API."""

    def __init__(self, config: ZimbraConfig):
        """Initialize the Zimbra client.

        Args:
            config: Zimbra connection configuration
        """
        self.config = config
        self._comm: Communication | None = None
        self._token: str | None = None

    def connect(self) -> None:
        """Establish connection and authentication."""
        try:
            self._comm = Communication(self.config.url)

            self._token = auth.authenticate(
                self.config.url,
                self.config.user,
                self.config.password,
                use_password=True,
            )

            if not self._token:
                raise ZimbraAuthError("Zimbra authentication failed")

        except ZimbraAuthError:
            raise
        except Exception as e:
            raise ZimbraConnectionError(f"Unable to connect to Zimbra: {e}")

    def disconnect(self) -> None:
        """Close the connection."""
        self._comm = None
        self._token = None

    @property
    def is_connected(self) -> bool:
        """Check if the client is connected."""
        return self._token is not None

    def _ensure_connected(self) -> None:
        """Ensure the client is connected."""
        if not self.is_connected:
            self.connect()

    def request(self, request_name: str, namespace: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        """Send a SOAP request to Zimbra.

        Args:
            request_name: Request name (e.g., SearchRequest)
            namespace: Request namespace (e.g., urn:zimbraMail)
            params: Request parameters

        Returns:
            Zimbra response as a dictionary
        """
        self._ensure_connected()

        if self._comm is None:
            raise ZimbraConnectionError("Client not initialized")

        try:
            request = self._comm.gen_request(token=self._token)

            request_params = params or {}
            request.add_request(request_name, request_params, namespace)

            response = self._comm.send_request(request)

            if response.is_fault():
                # Get error details from the response
                fault_response = response.get_response()
                fault = fault_response.get("Fault", fault_response)
                reason = fault.get("Reason", {})
                error_msg = reason.get("Text", str(fault)) if isinstance(reason, dict) else str(fault)
                if "no such" in error_msg.lower() or "not found" in error_msg.lower():
                    raise ZimbraNotFoundError(error_msg)
                raise ZimbraOperationError(error_msg)

            response_name = request_name.replace("Request", "Response")
            return response.get_response().get(response_name, {})

        except (ZimbraNotFoundError, ZimbraOperationError):
            raise
        except Exception as e:
            raise ZimbraOperationError(f"Error during request {request_name}: {e}")

    def search_messages(
        self,
        query: str,
        limit: int = 50,
        offset: int = 0,
        types: str = "message",
    ) -> dict[str, Any]:
        """Search for messages.

        Args:
            query: Zimbra search query (e.g., "in:inbox from:john")
            limit: Maximum number of results
            offset: Offset for pagination
            types: Types of items to search

        Returns:
            Search results
        """
        params = {
            "query": query,
            "limit": limit,
            "offset": offset,
            "types": types,
            "fetch": "all",
        }
        return self.request("SearchRequest", "urn:zimbraMail", params)

    def get_message(self, msg_id: str, raw: bool = False) -> dict[str, Any]:
        """Retrieve a message by its ID.

        Args:
            msg_id: Message ID
            raw: If True, retrieve the raw message (MIME)

        Returns:
            Message details
        """
        params = {
            "m": {"id": msg_id, "html": 1, "raw": 1 if raw else 0},
        }
        return self.request("GetMsgRequest", "urn:zimbraMail", params)

    def get_folder(self, folder_path: str = "/") -> dict[str, Any]:
        """Retrieve a folder and its subfolders.

        Args:
            folder_path: Folder path

        Returns:
            Folder information
        """
        params = {"folder": {"path": folder_path}}
        return self.request("GetFolderRequest", "urn:zimbraMail", params)

    def move_messages(self, msg_ids: list[str], folder_id: str) -> dict[str, Any]:
        """Move messages to a folder.

        Args:
            msg_ids: List of message IDs
            folder_id: Destination folder ID

        Returns:
            Operation result
        """
        params = {
            "action": {
                "id": ",".join(msg_ids),
                "op": "move",
                "l": folder_id,
            }
        }
        return self.request("MsgActionRequest", "urn:zimbraMail", params)

    def mark_as_read(self, msg_ids: list[str], read: bool = True) -> dict[str, Any]:
        """Mark messages as read or unread.

        Args:
            msg_ids: List of message IDs
            read: True to mark as read, False for unread

        Returns:
            Operation result
        """
        op = "read" if read else "!read"
        params = {
            "action": {
                "id": ",".join(msg_ids),
                "op": op,
            }
        }
        return self.request("MsgActionRequest", "urn:zimbraMail", params)

    def create_draft(
        self,
        to: list[str],
        subject: str,
        body: str,
        cc: list[str] | None = None,
        bcc: list[str] | None = None,
    ) -> dict[str, Any]:
        """Create an email draft.

        Args:
            to: Recipients
            subject: Subject
            body: Message body
            cc: CC recipients
            bcc: BCC recipients

        Returns:
            Information about the created draft
        """
        addresses = [{"t": "f", "a": self.config.user}]
        addresses.extend([{"t": "t", "a": addr} for addr in to])
        if cc:
            addresses.extend([{"t": "c", "a": addr} for addr in cc])
        if bcc:
            addresses.extend([{"t": "b", "a": addr} for addr in bcc])

        params = {
            "m": {
                "e": addresses,
                "su": subject,
                "mp": {
                    "ct": "text/plain",
                    "content": body,
                },
            }
        }
        return self.request("SaveDraftRequest", "urn:zimbraMail", params)

    def get_all_tags(self) -> dict[str, Any]:
        """Retrieve all tags."""
        return self.request("GetTagRequest", "urn:zimbraMail")

    def create_tag(self, name: str, color: int | None = None) -> dict[str, Any]:
        """Create a new tag.

        Args:
            name: Tag name
            color: Tag color (0-127)

        Returns:
            Information about the created tag
        """
        tag_params: dict[str, Any] = {"name": name}
        if color is not None:
            tag_params["color"] = color

        params = {"tag": tag_params}
        return self.request("CreateTagRequest", "urn:zimbraMail", params)

    def delete_tag(self, tag_id: str) -> dict[str, Any]:
        """Delete a tag.

        Args:
            tag_id: Tag ID

        Returns:
            Operation result
        """
        params = {"action": {"op": "delete", "id": tag_id}}
        return self.request("TagActionRequest", "urn:zimbraMail", params)

    def tag_messages(self, msg_ids: list[str], tag_name: str, untag: bool = False) -> dict[str, Any]:
        """Add or remove a tag on messages.

        Args:
            msg_ids: List of message IDs
            tag_name: Tag name
            untag: If True, remove the tag instead of adding it

        Returns:
            Operation result
        """
        op = "!tag" if untag else "tag"
        params = {
            "action": {
                "id": ",".join(msg_ids),
                "op": op,
                "tn": tag_name,
            }
        }
        return self.request("MsgActionRequest", "urn:zimbraMail", params)

    def search_calendar(
        self,
        start_time: int,
        end_time: int,
        folder_id: str = "10",
    ) -> dict[str, Any]:
        """Search for calendar events.

        Args:
            start_time: Start timestamp (ms)
            end_time: End timestamp (ms)
            folder_id: Calendar folder ID (10 by default)

        Returns:
            List of events
        """
        params = {
            "query": f"inid:{folder_id}",
            "types": "appointment",
            "calExpandInstStart": start_time,
            "calExpandInstEnd": end_time,
        }
        return self.request("SearchRequest", "urn:zimbraMail", params)

    def get_appointment(self, appt_id: str) -> dict[str, Any]:
        """Retrieve event details.

        Args:
            appt_id: Event ID

        Returns:
            Event details
        """
        params = {"id": appt_id}
        return self.request("GetAppointmentRequest", "urn:zimbraMail", params)

    def create_appointment(
        self,
        subject: str,
        start_time: int,
        end_time: int,
        location: str | None = None,
        description: str | None = None,
        attendees: list[str] | None = None,
        all_day: bool = False,
    ) -> dict[str, Any]:
        """Create a calendar event.

        Args:
            subject: Event title
            start_time: Start timestamp (ms)
            end_time: End timestamp (ms)
            location: Location
            description: Description
            attendees: List of attendees
            all_day: All-day event

        Returns:
            Information about the created event
        """
        from datetime import datetime

        # Convert timestamps to Zimbra format (YYYYMMDD'T'HHMMSS or YYYYMMDD)
        start_dt = datetime.fromtimestamp(start_time / 1000)
        end_dt = datetime.fromtimestamp(end_time / 1000)

        if all_day:
            start_str = start_dt.strftime("%Y%m%d")
            end_str = end_dt.strftime("%Y%m%d")
        else:
            start_str = start_dt.strftime("%Y%m%dT%H%M%S")
            end_str = end_dt.strftime("%Y%m%dT%H%M%S")

        inv = {
            "comp": {
                "name": subject,
                "s": {"d": start_str},
                "e": {"d": end_str},
            }
        }

        if location:
            inv["comp"]["loc"] = location

        if description:
            inv["comp"]["desc"] = description

        if attendees:
            inv["comp"]["at"] = [{"a": addr, "role": "REQ"} for addr in attendees]

        if all_day:
            inv["comp"]["allDay"] = "1"

        params = {"m": {"inv": inv, "su": subject}}
        return self.request("CreateAppointmentRequest", "urn:zimbraMail", params)

    def get_free_busy(
        self,
        email: str,
        start_time: int,
        end_time: int,
    ) -> dict[str, Any]:
        """Retrieve user availability.

        Args:
            email: User email
            start_time: Start timestamp (ms)
            end_time: End timestamp (ms)

        Returns:
            Availability information
        """
        params = {
            "s": start_time,
            "e": end_time,
            "uid": email,
        }
        return self.request("GetFreeBusyRequest", "urn:zimbraMail", params)

    def get_attachment_content(self, msg_id: str, part_id: str) -> tuple[bytes, str, str]:
        """Retrieve attachment content via REST API.

        Args:
            msg_id: Message ID
            part_id: Part ID of the attachment

        Returns:
            Tuple of (content_bytes, filename, content_type)
        """
        import base64
        import urllib.request
        import urllib.error
        from urllib.parse import urlencode

        self._ensure_connected()

        # Build REST URL for attachment download
        # Format: /service/home/~/?id=<msg_id>&part=<part_id>&auth=qp&zauthtoken=<token>
        base_url = self.config.url.replace("/service/soap", "")
        params = urlencode({
            "id": msg_id,
            "part": part_id,
            "auth": "qp",
            "zauthtoken": self._token,
        })
        url = f"{base_url}/service/home/~/?{params}"

        try:
            req = urllib.request.Request(url)
            with urllib.request.urlopen(req, timeout=self.config.timeout) as response:
                content = response.read()
                content_type = response.headers.get("Content-Type", "application/octet-stream")

                # Extract filename from Content-Disposition header
                content_disp = response.headers.get("Content-Disposition", "")
                filename = "attachment"
                if "filename=" in content_disp:
                    import re
                    match = re.search(r'filename[*]?=["\']?([^"\';\n]+)', content_disp)
                    if match:
                        filename = match.group(1).strip()

                return content, filename, content_type

        except urllib.error.HTTPError as e:
            if e.code == 404:
                raise ZimbraNotFoundError(f"Attachment not found: msg_id={msg_id}, part_id={part_id}")
            raise ZimbraOperationError(f"Failed to download attachment: {e}")
        except Exception as e:
            raise ZimbraOperationError(f"Failed to download attachment: {e}")
