# Zimbra MCP Server

MCP (Model Context Protocol) server for Zimbra to manage emails, tags, calendar, and contacts.

## Installation

```bash
cd ~/Projets/MCP/zimbra-mcp

# With uv
uv sync

# Or with pip
pip install -e .
```

## Configuration

Create a `.env` file from the example:

```bash
cp .env.example .env
```

Configure your Zimbra credentials:

```env
ZIMBRA_URL=https://zimbra.example.com/service/soap
ZIMBRA_USER=me@example.com
ZIMBRA_PASSWORD=your_password
ZIMBRA_TIMEOUT=30
ZIMBRA_ENABLE_SEND=false
```

| Variable | Description | Default |
|----------|-------------|---------|
| `ZIMBRA_URL` | Zimbra SOAP endpoint URL | (required) |
| `ZIMBRA_USER` | Zimbra account email | (required) |
| `ZIMBRA_PASSWORD` | Zimbra account password | (required) |
| `ZIMBRA_TIMEOUT` | Request timeout in seconds | `30` |
| `ZIMBRA_ENABLE_SEND` | Enable `send_email` tool (`true`/`1`/`yes`) | `false` |

## Usage

### Start the server

```bash
uv run zimbra-mcp
```

### Test with MCP Inspector

```bash
mcp dev src/zimbra_mcp/server.py
```

## Available Tools

### Emails

| Tool | Description |
|------|-------------|
| `search_emails` | Search with Zimbra syntax (in:inbox, from:, tag:, etc.) |
| `get_email` | Retrieve an email by ID with full body |
| `download_attachment` | Download an attachment to a local file |
| `list_folders` | List all mail folders |
| `search_folder` | Search for a folder by name or path (case-insensitive partial match) |
| `move_emails` | Move emails to a folder |
| `mark_as_read` | Mark emails as read or unread |
| `delete_emails` | Delete emails (soft delete to Trash, or hard delete) |
| `create_draft` | Create a draft with optional reply/forward support |
| `send_email` | Send an email directly (opt-in, requires `ZIMBRA_ENABLE_SEND=true`) |

#### Reply & Forward Drafts

`create_draft` and `send_email` support linking to an original message for replies and forwards:

| Parameter | Description |
|-----------|-------------|
| `orig_msg_id` | ID of the original message |
| `reply_type` | `"r"` for reply, `"w"` for forward |
| `include_original` | `"inline"` to quote in body, `"attachment"` to attach as .eml |

Examples:
- **Simple draft:** `create_draft(to=[...], subject="...", body="...")`
- **Reply with quote:** `create_draft(to=[...], subject="Re: ...", body="...", orig_msg_id="123", reply_type="r", include_original="inline")`
- **Forward as attachment:** `create_draft(to=[...], subject="Fwd: ...", body="...", orig_msg_id="123", reply_type="w", include_original="attachment")`

#### Zimbra Search Syntax

**Basic operators:**
- `in:inbox` - Emails in inbox
- `from:john@example.com` - Emails from John
- `to:me` - Emails sent to me
- `tag:important` - Emails with "important" tag
- `subject:meeting` - Subject containing "meeting"
- `has:attachment` - Emails with attachments
- `after:2024-01-01 before:2024-12-31` - Date range (ISO or MM/DD/YYYY)
- `is:unread` - Unread emails
- `is:flagged` - Flagged emails

**Boolean operators:**
- `from:john OR from:mary` - Emails from John OR Mary
- `NOT is:read` or `-is:read` - Unread emails (exclusion)
- `(from:john OR from:mary) subject:urgent` - Parentheses for grouping

**Combinations:** `in:inbox from:boss tag:urgent is:unread`

### Contacts

| Tool | Description |
|------|-------------|
| `search_contacts` | Search contacts (all fields). Use `"*"` or empty for all |
| `get_contact` | Retrieve a contact by ID |
| `create_contact` | Create a contact (name, email, phone, company, etc.) |
| `update_contact` | Update specific fields of an existing contact |
| `delete_contact` | Delete one or more contacts |

### Tags

| Tool | Description |
|------|-------------|
| `list_tags` | List all tags with colors |
| `create_tag` | Create a tag (name, color) |
| `delete_tag` | Delete a tag |
| `add_tag_to_emails` | Add a tag to emails |
| `remove_tag_from_emails` | Remove a tag |

Available colors: blue, cyan, green, purple, red, yellow, pink, gray, orange

### Calendar

| Tool | Description |
|------|-------------|
| `get_calendar_events` | Events over a period |
| `get_event_details` | Full details of an event |
| `create_event` | Create an event |
| `get_free_busy` | User availability |

## Development

### Running tests

```bash
# Install test dependencies
uv sync --extra test

# Run tests
uv run pytest

# Verbose output
uv run pytest -v
```

### Test structure

Tests use `unittest.mock` to mock the Zimbra SOAP client, so no Zimbra server is needed. The `capture_tools` fixture in `conftest.py` intercepts `@mcp.tool()` decorators to access tool functions directly.

## Claude Code Integration

Add to your MCP configuration (`~/.claude/settings.json`):

```json
{
  "mcpServers": {
    "zimbra": {
      "command": "uv",
      "args": ["run", "--directory", "/home/me/Projets/MCP/zimbra-mcp", "zimbra-mcp"],
      "env": {
        "ZIMBRA_URL": "https://zimbra.example.com/service/soap",
        "ZIMBRA_USER": "me@example.com",
        "ZIMBRA_PASSWORD": "your_password"
      }
    }
  }
}
```

## Project Structure

```
zimbra-mcp/
├── pyproject.toml
├── README.md
├── CLAUDE.md
├── .env.example
├── src/
│   └── zimbra_mcp/
│       ├── __init__.py
│       ├── server.py          # FastMCP entry point
│       ├── config.py          # Configuration
│       ├── client.py          # Zimbra SOAP client
│       ├── errors.py          # Exceptions
│       └── tools/
│           ├── __init__.py
│           ├── emails.py      # Email tools
│           ├── tags.py        # Tag tools
│           ├── contacts.py    # Contact tools
│           └── calendar.py    # Calendar tools
└── tests/
    ├── conftest.py            # Shared fixtures
    ├── test_config.py
    ├── test_errors.py
    ├── test_client.py
    └── tools/
        ├── test_emails.py
        ├── test_tags.py
        ├── test_contacts.py
        └── test_calendar.py
```
