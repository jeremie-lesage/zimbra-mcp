"""Diagnose which Zimbra REST attachment-download URL form works on this server.

Usage:
    uv run python scripts/diag_attachment.py <msg_id> <part_id>

Authenticates with the configured account (prompting for a TOTP code if the
account uses 2FA), then issues several variants of the content-servlet request
and reports the HTTP status / content-type / size for each. The first variant
that returns 200 with the expected content-type is the one the code should use.
"""

import sys
import urllib.error
import urllib.request
from urllib.parse import quote, urlencode, urlsplit

from zimbra_mcp.client import ZimbraClient
from zimbra_mcp.config import ZimbraConfig
from zimbra_mcp.errors import ZimbraTwoFactorRequiredError


def main() -> None:
    if len(sys.argv) != 3:
        print(__doc__)
        sys.exit(1)
    msg_id, part_id = sys.argv[1], sys.argv[2]

    config = ZimbraConfig.from_env()
    client = ZimbraClient(config)
    try:
        client.connect()
    except ZimbraTwoFactorRequiredError:
        code = input("TOTP code: ").strip()
        client.authenticate(totp_code=code)

    token = client._token
    # Derive base from scheme+host only — robust to trailing slashes and to URLs
    # that do/don't include the /service/soap path.
    parts = urlsplit(config.url)
    base_url = f"{parts.scheme}://{parts.netloc}"
    user_enc = quote(config.user)

    # (label, path, query-params dict, extra headers)
    variants = [
        (
            "qp + ~",
            f"{base_url}/service/home/~/",
            {"id": msg_id, "part": part_id, "auth": "qp", "zauthtoken": token},
            {},
        ),
        (
            "qp + user",
            f"{base_url}/service/home/{user_enc}/",
            {"id": msg_id, "part": part_id, "auth": "qp", "zauthtoken": token},
            {},
        ),
        (
            "cookie + ~",
            f"{base_url}/service/home/~/",
            {"id": msg_id, "part": part_id, "auth": "co"},
            {"Cookie": f"ZM_AUTH_TOKEN={token}"},
        ),
        (
            "cookie + user",
            f"{base_url}/service/home/{user_enc}/",
            {"id": msg_id, "part": part_id, "auth": "co"},
            {"Cookie": f"ZM_AUTH_TOKEN={token}"},
        ),
        (
            "qp + ~ + disp=a",
            f"{base_url}/service/home/~/",
            {"id": msg_id, "part": part_id, "auth": "qp", "zauthtoken": token, "disp": "a"},
            {},
        ),
    ]

    print(f"base_url = {base_url}")
    print(f"account  = {config.user}")
    print(f"msg_id={msg_id} part_id={part_id}\n")

    for label, path, params, headers in variants:
        url = f"{path}?{urlencode(params)}"
        # Redact the token in the printed URL.
        shown = url.replace(token, "<token>") if token else url
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=config.timeout) as resp:
                body = resp.read(2048)
                ct = resp.headers.get("Content-Type", "?")
                cl = resp.headers.get("Content-Length", "?")
                print(f"[{label:18}] 200  ct={ct}  len={cl}")
                if "text/html" in ct:
                    print(f"    (HTML body — likely a login/redirect page, not the file)")
        except urllib.error.HTTPError as e:
            loc = e.headers.get("Location", "") if e.headers else ""
            print(f"[{label:18}] {e.code}  {e.reason}  {('-> ' + loc) if loc else ''}")
        except Exception as e:  # noqa: BLE001
            print(f"[{label:18}] ERROR {type(e).__name__}: {e}")
        print(f"    {shown}")


if __name__ == "__main__":
    main()
