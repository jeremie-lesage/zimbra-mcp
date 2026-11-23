# Zimbra MCP Server

MCP (Model Context Protocol) server for Zimbra to manage emails, tags, mail filters, calendar, and contacts.

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
| `ZIMBRA_TIMEOUT` | Request timeout in seconds (SOAP, auth and downloads) | `30` |
| `ZIMBRA_ENABLE_SEND` | Enable `send_email` tool (`true`/`1`/`yes`) | `false` |
| `ZIMBRA_ENABLE_HARD_DELETE` | Allow permanent deletion of emails/contacts (`hard_delete=True`) | `false` |
| `ZIMBRA_ENABLE_FILTERS` | Enable the filter write tools (`add_filter`, `move_filter`, `update_filter`, `delete_filter`, `add_filter_condition`, `remove_filter_condition`) | `false` |
| `ZIMBRA_APPEND_SIGNATURE` | Add the account signature to drafts and sent mail when the call does not set `append_signature` | `false` |
| `ZIMBRA_DOWNLOAD_DIR` | When set, the only directory `download_attachment` may write into | (unset) |
| `ZIMBRA_MAX_ATTACHMENT_MB` | Maximum attachment size downloaded | `50` |
| `ZIMBRA_ALLOW_INSECURE_HTTP` | Accept a plain `http://` `ZIMBRA_URL` (credentials sent unencrypted) | `false` |

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

### Authentication

| Tool | Description |
|------|-------------|
| `zimbra_authenticate` | Complete a two-factor login with the current code from an authenticator app |
| `zimbra_auth_status` | Report whether a Zimbra session is active and for which account |

Accounts without two-factor authentication log in at startup and need neither tool. For a 2FA
account, the server starts without a session: the first tool call fails with an authentication
error, the user gives the current TOTP code and `zimbra_authenticate` opens the session. When the
session expires, call `zimbra_authenticate` again with a new code. Accounts without 2FA
re-authenticate automatically.

### Emails

| Tool | Description |
|------|-------------|
| `search_emails` | Search with Zimbra syntax (in:inbox, from:, tag:, etc.), optionally restricted to a folder (`folder_id`) and its subfolders (`include_subfolders`), shared folders included |
| `get_email` | Retrieve an email by ID with full body |
| `download_attachment` | Download an attachment to a local file (never overwrites, confined to `ZIMBRA_DOWNLOAD_DIR` when set) |
| `list_folders` | List mail folders, shared folders included, one level at a time: `path` picks the parent, `depth` the number of levels (`None` for the whole tree) |
| `search_folder` | Search for a folder by name or path (case-insensitive partial match) |
| `create_folder` | Create a mail folder (`name`, `parent` path or ID, `color`); under a shared folder it is created in the owner's mailbox, and an existing folder is returned with `"created": false` |
| `move_emails` | Move emails to a folder |
| `mark_as_read` | Mark emails as read or unread |
| `delete_emails` | Delete emails (Trash by default; hard delete requires `ZIMBRA_ENABLE_HARD_DELETE=true`) |
| `create_draft` | Create or update a draft (plain text or HTML), with optional reply/forward support |
| `send_email` | Send an email directly (opt-in, requires `ZIMBRA_ENABLE_SEND=true`) |

#### Formatted (HTML) mail

`create_draft` and `send_email` accept `body_html` next to `body`. The message is then saved as
`multipart/alternative` with both an HTML and a plain-text part. If `body` is empty, the plain text
is generated from the HTML.

- **Sanitised:** `body_html` is reduced to a formatting subset (paragraphs, bold/italic, lists,
  links, tables, headings, inline styles). Scripts, event handlers, `<style>` blocks, images,
  `javascript:` links and style properties such as `background-image: url(...)` are removed.
- **Replies keep the thread's formatting:** with `include_original="inline"`, the original's HTML
  is quoted under a From/To/Sent/Subject header. Inline `cid:` images in the original are dropped
  (the reply does not carry those parts); ordinary `https` images are kept.
- **Update in place:** pass `draft_id` to `create_draft` to replace an existing draft's content
  instead of creating a new one.

#### Signature

Pass `append_signature=True` to `create_draft` or `send_email` to add the account signature the
way the Zimbra web client does. Set `ZIMBRA_APPEND_SIGNATURE=true` to make that the default; a call
can still pass `append_signature=False`.

- **Which signature:** the default identity's default signature, or its reply/forward signature
  when `orig_msg_id` is set. An account with a single signature and no default uses it. When the
  reply/forward setting is "no signature", nothing is added.
- **Where:** above the quoted original, or below it when the account's signature style is
  "internet" (`zimbraPrefMailSignatureStyle`).
- **Format:** an HTML signature is sanitised like quoted originals (`https` images are kept) and
  turns a plain-text message into HTML; the plain-text part gets the signature after a `-- `
  delimiter.

The response contains `signature`: the name of the signature added, or `null` when none applies.

#### Reply & Forward Drafts

`create_draft` and `send_email` support linking to an original message for replies and forwards:

| Parameter | Description |
|-----------|-------------|
| `orig_msg_id` | ID of the original message |
| `reply_type` | `"r"` for reply, `"w"` for forward |
| `include_original` | `"inline"` to quote in body (default), `"attachment"` to attach as .eml, `"none"` to leave it out |

Examples:
- **Simple draft:** `create_draft(to=[...], subject="...", body="...")`
- **Reply with quote:** `create_draft(to=[...], subject="Re: ...", body="...", orig_msg_id="123", reply_type="r", include_original="inline")`
- **Forward as attachment:** `create_draft(to=[...], subject="Fwd: ...", body="...", orig_msg_id="123", reply_type="w", include_original="attachment")`
- **HTML reply:** `create_draft(to=[...], subject="Re: ...", body_html="<p>Thanks, <b>agreed</b>.</p>", orig_msg_id="123", reply_type="r")`
- **Revise a draft:** `create_draft(to=[...], subject="Re: ...", body_html="<p>Revised</p>", draft_id="456")`
- **Signed draft:** `create_draft(to=[...], subject="...", body_html="<p>Hello</p>", append_signature=True)`

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
| `delete_contact` | Delete contacts (Trash by default; hard delete requires `ZIMBRA_ENABLE_HARD_DELETE=true`) |

### Tags

| Tool | Description |
|------|-------------|
| `list_tags` | List all tags with colors |
| `create_tag` | Create a tag (name, color) |
| `delete_tag` | Delete a tag |
| `add_tag_to_emails` | Add a tag to emails |
| `remove_tag_from_emails` | Remove a tag |

Available colors: blue, cyan, green, purple, red, yellow, pink, gray, orange

### Filters

| Tool | Description |
|------|-------------|
| `list_filters` | List incoming mail filters in execution order |
| `find_matching_filters` | Show which filters would catch an email (received or hypothetical) and which one stops processing, without applying anything |
| `add_filter` | Add a filter, at the end of the list or at a given place (opt-in, requires `ZIMBRA_ENABLE_FILTERS=true`) |
| `move_filter` | Move a filter before another one or to a position (opt-in) |
| `update_filter` | Rename, enable/disable, or replace the conditions or actions of a filter (opt-in) |
| `delete_filter` | Delete a filter (opt-in) |
| `add_filter_condition` | Add one condition to a filter, keeping the others (opt-in) |
| `remove_filter_condition` | Remove one condition from a filter, keeping the others (opt-in) |

A condition is `{"field": ..., "value": ..., "comparison": ..., "part": ...}`:

- `field`: `sender` (From address), `recipient` (To or Cc address), `subject`, `list_id`, or any header name (`X-Spam-Flag`, `Reply-To`)
- `comparison`: `contains` (default) or `is`, case-insensitive
- `part`: for `sender` and `recipient`, `all` (default) or `domain`

```json
[{"field": "sender", "value": "spammer.com", "part": "domain"},
 {"field": "X-VRSPAM-STATE", "value": "spam", "comparison": "is"}]
```

Conditions are matched with `all` or `any`. Actions: move to a folder, tag, mark as read, flag, keep a copy in the Inbox, move to the Trash, stop processing the next filters. Filters are identified by their name.

Zimbra only accepts the whole filter list on write: each write tool reads the list, changes one filter and sends the list back, leaving the other filters untouched, including conditions and actions these tools cannot create. A change made in the web client between that read and that write is lost.

Zimbra has no dry run for filters, so `find_matching_filters` evaluates them itself from the email headers. Conditions on the body, size, date or address book cannot be evaluated: the filter is then reported as `unknown`, never as not matching.

### Calendar

| Tool | Description |
|------|-------------|
| `get_calendar_events` | Events over a period |
| `get_event_details` | Full details of an event |
| `create_event` | Create an event, optionally private, with attendees invited by email if requested |
| `update_event` | Change the title, time, location, description or privacy of an event you organize |
| `delete_event` | Move an event to the Trash |
| `get_free_busy` | User availability |

`update_event` only changes the fields it is given and keeps the rest of the event (recurrence, reminder, attendees). A recurring event is modified as a whole series, and attendees are not notified of the change.

## Security

The content of emails is controlled by their senders. A malicious email can contain instructions aimed at the LLM (*prompt injection*), so the server limits what a manipulated model can do:

- **No sending by default**: `send_email` only exists when `ZIMBRA_ENABLE_SEND=true`, and `create_event` only emails invitations when it is set. Drafts are always safe to create.
- **No irreversible deletion by default**: `hard_delete=True` is refused unless `ZIMBRA_ENABLE_HARD_DELETE=true`; emails and contacts go to the Trash.
- **No filter changes by default**: a filter acts on every future email, so the filter write tools only exist when `ZIMBRA_ENABLE_FILTERS=true`. They never discard, redirect or reply: "delete" means moving to the Trash.
- **File writes**: `download_attachment` strips any path from the file name (`../../.bashrc` becomes `bashrc`), never overwrites an existing file and caps the size (`ZIMBRA_MAX_ATTACHMENT_MB`). Set `ZIMBRA_DOWNLOAD_DIR` to confine writes to a single directory.
- **Credentials**: HTTPS is required unless explicitly overridden; the auth token is sent as a cookie (never in a URL that could end up in proxy logs), redirects are refused so it cannot be forwarded to another host; the password is never included in `repr()`.
- **Timeouts** on every request, so a hung server cannot block the MCP client forever.

Keep `.env` out of version control (it is in `.gitignore`) and prefer an application-specific password if your Zimbra supports it.

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
├── AGENTS.md
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
│           ├── auth.py        # Two-factor login tools
│           ├── emails.py      # Email tools
│           ├── tags.py        # Tag tools
│           ├── filters.py     # Mail filter tools
│           ├── contacts.py    # Contact tools
│           └── calendar.py    # Calendar tools
└── tests/
    ├── conftest.py            # Shared fixtures
    ├── test_config.py
    ├── test_errors.py
    ├── test_client.py
    └── tools/
        ├── test_auth.py
        ├── test_emails.py
        ├── test_tags.py
        ├── test_filters.py
        ├── test_contacts.py
        └── test_calendar.py
```

## Contributing

See [AGENTS.md](AGENTS.md) for the conventions to follow, whether you write the code yourself or
with an AI assistant. Pull requests target the `develop` branch.

## Acknowledgements

Many thanks to the people who contributed to this project:

- **Fritz Kunstler** ([@dfkunstler](https://github.com/dfkunstler)): two-factor authentication,
  attachment download hardening and the REST URL fix ([#1](https://github.com/jeremie-lesage/zimbra-mcp/pull/1))
- **Cindy Piassale** ([@cindyPiassale](https://github.com/cindyPiassale)): shared folders and
  subfolder search ([#2](https://github.com/jeremie-lesage/zimbra-mcp/pull/2))
- **Sam Gelbart** ([@synaq](https://github.com/synaq)): HTML bodies, HTML reply quoting,
  sanitising and draft updates ([#3](https://github.com/jeremie-lesage/zimbra-mcp/pull/3))
- **Ilies** ([@Saywyz](https://github.com/Saywyz)): security hardening of attachments, deletion,
  authentication and configuration ([#4](https://github.com/jeremie-lesage/zimbra-mcp/pull/4))
