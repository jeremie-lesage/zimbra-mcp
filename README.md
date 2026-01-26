# Zimbra MCP Server

MCP (Model Context Protocol) server for Zimbra to manage emails, tags, and calendar.

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
```

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
| `list_folders` | List all mail folders |
| `move_emails` | Move emails to a folder |
| `create_draft` | Create a draft (without sending) |

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
├── .env.example
└── src/
    └── zimbra_mcp/
        ├── __init__.py
        ├── server.py          # FastMCP entry point
        ├── config.py          # Configuration
        ├── client.py          # Zimbra SOAP client
        ├── errors.py          # Exceptions
        └── tools/
            ├── __init__.py
            ├── emails.py      # Email tools
            ├── tags.py        # Tag tools
            └── calendar.py    # Calendar tools
```

