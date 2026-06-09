"""Zimbra SOAP Client."""

from typing import Any

from pythonzimbra.communication import Communication

from zimbra_mcp.config import ZimbraConfig
from zimbra_mcp.errors import (
    ZimbraAuthError,
    ZimbraConnectionError,
    ZimbraNotFoundError,
    ZimbraOperationError,
    ZimbraTwoFactorRequiredError,
)

# Maximum attachment size to download into memory (100 MiB). Guards against a
# hostile or accidentally huge attachment exhausting memory.
MAX_ATTACHMENT_SIZE_BYTES = 100 * 1024 * 1024


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
        """Establish a connection and authenticate without a 2FA code.

        For accounts without two-factor auth this completes login. For 2FA
        accounts the server returns a 2FA-pending token, so this raises
        ``ZimbraTwoFactorRequiredError`` — complete login by calling
        :meth:`authenticate` with a current code instead.
        """
        self.authenticate()

    def authenticate(self, totp_code: str | None = None) -> None:
        """Authenticate to Zimbra, optionally completing two-factor auth.

        Sends a single ``AuthRequest`` (``urn:zimbraAccount``) with the account
        password and, when supplied, a ``twoFactorCode``. On a 2FA-enabled
        account a password-only request succeeds but returns a short-lived
        *partial* token flagged ``twoFactorAuthRequired``; we reject that and
        raise ``ZimbraTwoFactorRequiredError`` so the caller knows to supply a
        current code. A correct password + code yields a full session token
        (~48h on a default Zimbra config).

        Args:
            totp_code: Current 6-digit code from the user's authenticator app.
        """
        try:
            if self._comm is None:
                self._comm = Communication(self.config.url)

            request = self._comm.gen_request()  # unauthenticated — no token yet
            params: dict[str, Any] = {
                "account": {"by": "name", "_content": self.config.user},
                "password": {"_content": self.config.password},
            }
            if totp_code:
                params["twoFactorCode"] = {"_content": totp_code}
            request.add_request("AuthRequest", params, "urn:zimbraAccount")

            response = self._comm.send_request(request)

            if response.is_fault():
                fault_response = response.get_response()
                fault = fault_response.get("Fault", fault_response)
                reason = fault.get("Reason", {})
                msg = reason.get("Text", str(fault)) if isinstance(reason, dict) else str(fault)
                raise ZimbraAuthError(f"Zimbra authentication failed for {self.config.user}: {msg}")

            resp = response.get_response().get("AuthResponse", {})

            # python-zimbra's response filter collapses single-"_content" dicts
            # to plain values, so twoFactorAuthRequired arrives as the string
            # "true" (and authToken as a bare string) — but tolerate both shapes.
            two_fa = resp.get("twoFactorAuthRequired")
            if isinstance(two_fa, dict):
                two_fa = two_fa.get("_content")
            # Password accepted but only a 2FA-pending token returned: demand a code.
            if str(two_fa).lower() == "true":
                raise ZimbraTwoFactorRequiredError(
                    "Two-factor authentication required: re-authenticate with a current "
                    "code from your authenticator app."
                )

            token = resp.get("authToken")
            if isinstance(token, list):
                token = token[0] if token else None
            if isinstance(token, dict):
                token = token.get("_content")
            if not token:
                raise ZimbraAuthError("Zimbra authentication failed: no auth token returned")

            self._token = token

        except (ZimbraAuthError, ZimbraTwoFactorRequiredError):
            raise
        except Exception as e:
            raise ZimbraConnectionError(f"Unable to connect to Zimbra ({self.config.url}): {e}")

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
                detail = fault.get("Detail", {})
                code = detail.get("Error", {}).get("Code", "") if isinstance(detail, dict) else ""
                # An expired/invalid session token (e.g. the ~48h 2FA session
                # lapsing) — drop it and tell the caller to re-authenticate.
                if code in ("service.AUTH_EXPIRED", "service.AUTH_REQUIRED"):
                    self._token = None
                    raise ZimbraAuthError(f"Zimbra session expired; re-authenticate: {error_msg}")
                if "no such" in error_msg.lower() or "not found" in error_msg.lower():
                    raise ZimbraNotFoundError(error_msg)
                raise ZimbraOperationError(error_msg)

            response_name = request_name.replace("Request", "Response")
            return response.get_response().get(response_name, {})

        except (ZimbraNotFoundError, ZimbraOperationError, ZimbraAuthError):
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

    def delete_messages(self, msg_ids: list[str], hard_delete: bool = False) -> dict[str, Any]:
        """Delete messages.

        Args:
            msg_ids: List of message IDs
            hard_delete: If True, permanently delete; otherwise move to Trash

        Returns:
            Operation result
        """
        op = "delete" if hard_delete else "trash"
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
        orig_msg_id: str | None = None,
        reply_type: str | None = None,
        attach_msg_id: str | None = None,
    ) -> dict[str, Any]:
        """Create an email draft.

        Args:
            to: Recipients
            subject: Subject
            body: Message body
            cc: CC recipients
            bcc: BCC recipients
            orig_msg_id: Original message ID (for reply/forward)
            reply_type: "r" for reply, "w" for forward
            attach_msg_id: Message ID to attach as .eml (RFC 822)

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
        if orig_msg_id:
            params["m"]["origid"] = orig_msg_id
        if reply_type:
            params["m"]["rt"] = reply_type
        if attach_msg_id:
            params["m"]["attach"] = {"m": {"id": attach_msg_id}}
        return self.request("SaveDraftRequest", "urn:zimbraMail", params)

    def send_message(
        self,
        to: list[str],
        subject: str,
        body: str,
        cc: list[str] | None = None,
        bcc: list[str] | None = None,
        orig_msg_id: str | None = None,
        reply_type: str | None = None,
        attach_msg_id: str | None = None,
        draft_id: str | None = None,
    ) -> dict[str, Any]:
        """Send an email message.

        Args:
            to: Recipients
            subject: Subject
            body: Message body
            cc: CC recipients
            bcc: BCC recipients
            orig_msg_id: Original message ID (for reply/forward)
            reply_type: "r" for reply, "w" for forward
            attach_msg_id: Message ID to attach as .eml (RFC 822)
            draft_id: Draft ID to send (marks draft as sent)

        Returns:
            Information about the sent message
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
        if orig_msg_id:
            params["m"]["origid"] = orig_msg_id
        if reply_type:
            params["m"]["rt"] = reply_type
        if attach_msg_id:
            params["m"]["attach"] = {"m": {"id": attach_msg_id}}
        if draft_id:
            params["m"]["did"] = draft_id
        return self.request("SendMsgRequest", "urn:zimbraMail", params)

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

    def search_contacts(
        self,
        query: str,
        limit: int = 50,
        offset: int = 0,
    ) -> dict[str, Any]:
        """Search for contacts.

        Args:
            query: Zimbra search query
            limit: Maximum number of results
            offset: Offset for pagination

        Returns:
            Search results
        """
        params = {
            "query": query,
            "limit": limit,
            "offset": offset,
            "types": "contact",
            "fetch": "all",
        }
        return self.request("SearchRequest", "urn:zimbraMail", params)

    def get_contact(self, contact_id: str) -> dict[str, Any]:
        """Retrieve a contact by its ID.

        Args:
            contact_id: Contact ID

        Returns:
            Contact details
        """
        params = {
            "cn": {"id": contact_id},
        }
        return self.request("GetContactsRequest", "urn:zimbraMail", params)

    def create_contact(self, folder_id: str | None, attributes: list[dict[str, str]]) -> dict[str, Any]:
        """Create a contact.

        Args:
            folder_id: Folder ID (None for default Contacts folder)
            attributes: List of {"n": name, "_content": value} dicts

        Returns:
            Information about the created contact
        """
        cn: dict[str, Any] = {"a": attributes}
        if folder_id:
            cn["l"] = folder_id

        params = {"cn": cn}
        return self.request("CreateContactRequest", "urn:zimbraMail", params)

    def modify_contact(self, contact_id: str, attributes: list[dict[str, str]]) -> dict[str, Any]:
        """Modify a contact.

        Args:
            contact_id: Contact ID
            attributes: List of {"n": name, "_content": value} dicts

        Returns:
            Updated contact information
        """
        params = {
            "cn": {
                "id": contact_id,
                "a": attributes,
            },
        }
        return self.request("ModifyContactRequest", "urn:zimbraMail", params)

    def delete_contacts(self, contact_ids: list[str]) -> dict[str, Any]:
        """Delete contacts.

        Args:
            contact_ids: List of contact IDs

        Returns:
            Operation result
        """
        params = {
            "action": {
                "id": ",".join(contact_ids),
                "op": "delete",
            }
        }
        return self.request("ContactActionRequest", "urn:zimbraMail", params)

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
                # Reject oversized attachments up front when the server advertises
                # a length, then cap the actual read so a missing/lying header
                # cannot blow past the limit either.
                declared = response.headers.get("Content-Length")
                if declared is not None and declared.isdigit() and int(declared) > MAX_ATTACHMENT_SIZE_BYTES:
                    raise ZimbraOperationError(
                        f"Attachment too large: {int(declared)} bytes exceeds limit of {MAX_ATTACHMENT_SIZE_BYTES}"
                    )
                content = response.read(MAX_ATTACHMENT_SIZE_BYTES + 1)
                if len(content) > MAX_ATTACHMENT_SIZE_BYTES:
                    raise ZimbraOperationError(
                        f"Attachment too large: exceeds limit of {MAX_ATTACHMENT_SIZE_BYTES} bytes"
                    )
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
        except (ZimbraNotFoundError, ZimbraOperationError):
            raise
        except Exception as e:
            raise ZimbraOperationError(f"Failed to download attachment: {e}")
