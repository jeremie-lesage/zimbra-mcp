"""MCP tools for Zimbra contact management."""

from typing import Any

from mcp.server.fastmcp import FastMCP

from zimbra_mcp.client import ZimbraClient

# Mapping from Python snake_case to Zimbra camelCase attribute names
_ATTR_MAP = {
    "first_name": "firstName",
    "last_name": "lastName",
    "email": "email",
    "mobile_phone": "mobilePhone",
    "work_phone": "workPhone",
    "home_phone": "homePhone",
    "company": "company",
    "job_title": "jobTitle",
    "notes": "notes",
}

# Reverse mapping for parsing responses
_ATTR_MAP_REVERSE = {v: k for k, v in _ATTR_MAP.items()}


def _build_contact_attrs(**kwargs: str | None) -> list[dict[str, str]]:
    """Convert keyword arguments to Zimbra contact attribute list.

    Only includes non-None values.
    """
    attrs = []
    for python_name, value in kwargs.items():
        if value is not None and python_name in _ATTR_MAP:
            attrs.append({"n": _ATTR_MAP[python_name], "_content": value})
    return attrs


def _parse_contact(cn: dict) -> dict[str, Any]:
    """Parse a Zimbra contact response into a readable dict."""
    contact: dict[str, Any] = {
        "id": cn.get("id"),
        "folder": cn.get("l"),
    }

    # pythonzimbra returns attributes as a flat dict in "_attrs"
    attrs = cn.get("_attrs", {})
    for zimbra_name, value in attrs.items():
        if zimbra_name in _ATTR_MAP_REVERSE:
            contact[_ATTR_MAP_REVERSE[zimbra_name]] = value
        else:
            contact[zimbra_name] = value

    return contact


def register_contact_tools(mcp: FastMCP, client: ZimbraClient) -> None:
    """Register contact management tools.

    Args:
        mcp: FastMCP instance
        client: Zimbra client
    """

    @mcp.tool()
    def search_contacts(
        query: str = "",
        limit: int = 50,
        offset: int = 0,
    ) -> dict[str, Any]:
        """Search contacts in the address book.

        Args:
            query: Search query (searches across all fields). Use "*" or empty string for all contacts.
            limit: Maximum number of results (default: 50)
            offset: Offset for pagination

        Returns:
            List of matching contacts
        """
        search_query = query if query else "*"
        result = client.search_contacts(search_query, limit=limit, offset=offset)

        contacts_raw = result.get("cn", [])
        if not isinstance(contacts_raw, list):
            contacts_raw = [contacts_raw] if contacts_raw else []

        contacts = [_parse_contact(cn) for cn in contacts_raw]

        return {
            "contacts": contacts,
            "total": result.get("total", len(contacts)),
            "more": result.get("more", False),
            "offset": offset,
        }

    @mcp.tool()
    def get_contact(contact_id: str) -> dict[str, Any]:
        """Retrieve a contact by its ID.

        Args:
            contact_id: Contact ID (obtained via search_contacts)

        Returns:
            Full contact details
        """
        result = client.get_contact(contact_id)

        cn = result.get("cn", {})
        if isinstance(cn, list):
            cn = cn[0] if cn else {}

        return _parse_contact(cn)

    @mcp.tool()
    def create_contact(
        first_name: str | None = None,
        last_name: str | None = None,
        email: str | None = None,
        mobile_phone: str | None = None,
        work_phone: str | None = None,
        home_phone: str | None = None,
        company: str | None = None,
        job_title: str | None = None,
        notes: str | None = None,
        folder_id: str | None = None,
    ) -> dict[str, Any]:
        """Create a new contact.

        Args:
            first_name: First name
            last_name: Last name
            email: Email address
            mobile_phone: Mobile phone number
            work_phone: Work phone number
            home_phone: Home phone number
            company: Company name
            job_title: Job title
            notes: Notes
            folder_id: Folder ID (default: Contacts folder)

        Returns:
            Information about the created contact
        """
        attrs = _build_contact_attrs(
            first_name=first_name,
            last_name=last_name,
            email=email,
            mobile_phone=mobile_phone,
            work_phone=work_phone,
            home_phone=home_phone,
            company=company,
            job_title=job_title,
            notes=notes,
        )

        if not attrs:
            return {
                "success": False,
                "error": "At least one field must be provided",
            }

        result = client.create_contact(folder_id, attrs)

        cn = result.get("cn", {})
        if isinstance(cn, list):
            cn = cn[0] if cn else {}

        contact = _parse_contact(cn)
        return {
            "success": True,
            "contact": contact,
        }

    @mcp.tool()
    def update_contact(
        contact_id: str,
        first_name: str | None = None,
        last_name: str | None = None,
        email: str | None = None,
        mobile_phone: str | None = None,
        work_phone: str | None = None,
        home_phone: str | None = None,
        company: str | None = None,
        job_title: str | None = None,
        notes: str | None = None,
    ) -> dict[str, Any]:
        """Update an existing contact.

        Only provided fields will be updated; others remain unchanged.

        Args:
            contact_id: Contact ID (obtained via search_contacts)
            first_name: First name
            last_name: Last name
            email: Email address
            mobile_phone: Mobile phone number
            work_phone: Work phone number
            home_phone: Home phone number
            company: Company name
            job_title: Job title
            notes: Notes

        Returns:
            Updated contact information
        """
        attrs = _build_contact_attrs(
            first_name=first_name,
            last_name=last_name,
            email=email,
            mobile_phone=mobile_phone,
            work_phone=work_phone,
            home_phone=home_phone,
            company=company,
            job_title=job_title,
            notes=notes,
        )

        if not attrs:
            return {
                "success": False,
                "error": "At least one field must be provided",
            }

        result = client.modify_contact(contact_id, attrs)

        cn = result.get("cn", {})
        if isinstance(cn, list):
            cn = cn[0] if cn else {}

        contact = _parse_contact(cn)
        return {
            "success": True,
            "contact": contact,
        }

    @mcp.tool()
    def delete_contact(contact_ids: list[str]) -> dict[str, Any]:
        """Delete one or more contacts.

        Args:
            contact_ids: List of contact IDs to delete

        Returns:
            Deletion confirmation
        """
        client.delete_contacts(contact_ids)

        return {
            "success": True,
            "deleted_count": len(contact_ids),
            "deleted_ids": contact_ids,
        }
