"""Authorize + exchange example for Workday (Authorization Code grant).

Usage (quick):
  # dry-run just prints the authorize URL
  python examples/authorize_exchange_workday.py --dry-run --client-id YOUR_ID

  # full flow (opens browser, starts local callback server, exchanges code)
  export WORKDAY_CLIENT_ID=...
  export WORKDAY_CLIENT_SECRET=...
  python examples/authorize_exchange_workday.py

Notes:
- CLIENT_ID can be passed via `--client-id` or `WORKDAY_CLIENT_ID` env var.
- CLIENT_SECRET can be read from `WORKDAY_CLIENT_SECRET` env var (recommended) or passed interactively.
- The script defaults to redirect URI http://127.0.0.1:8000/callback; change with `--port` or `--redirect-path`.
"""

from __future__ import annotations

import argparse
import json
import os
import socketserver
import sys
import threading
import urllib.parse as urlparse
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer

try:
    import requests
    from requests.auth import HTTPBasicAuth
except Exception:  # pragma: no cover - helpful for dry-run on minimal envs
    requests = None
    HTTPBasicAuth = None


DEFAULT_AUTH_URL = "https://wd5-impl.workday.com/michaels1/authorize"
DEFAULT_TOKEN_URL = "https://wd5-impl-services1.workday.com/ccx/oauth2/michaels1/token"


class CallbackHandler(BaseHTTPRequestHandler):
    server_version = "AuthCallback/0.1"

    def do_GET(self):
        params = urlparse.parse_qs(urlparse.urlparse(self.path).query)
        code = params.get("code", [None])[0]
        state = params.get("state", [None])[0]
        # Write a simple page and stop server
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.end_headers()
        if code:
            self.wfile.write(b"Authorization received. You may close this window.\n")
            # stash result on server for caller
            self.server._auth_code = code
            self.server._auth_state = state
        else:
            self.wfile.write(b"No code received.\n")


def build_authorize_url(auth_url: str, client_id: str, redirect_uri: str, scope: str, state: str) -> str:
    params = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "scope": scope,
        "state": state,
    }
    return auth_url + "?" + urlparse.urlencode(params)


def exchange_code(token_url: str, client_id: str, client_secret: str, code: str, redirect_uri: str, timeout: int = 10):
    if requests is None:
        raise RuntimeError("requests is required to perform the token exchange")
    data = {"grant_type": "authorization_code", "code": code, "redirect_uri": redirect_uri}
    resp = requests.post(token_url, data=data, auth=HTTPBasicAuth(client_id, client_secret), headers={"Accept": "application/json"}, timeout=timeout)
    resp.raise_for_status()
    return resp.json()


def main(argv: list[str] | None = None) -> int:
    argv = list(argv or sys.argv[1:])
    p = argparse.ArgumentParser()
    p.add_argument("--client-id", help="Workday client id (or use WORKDAY_CLIENT_ID env var)")
    p.add_argument("--client-secret", help="Client secret (not recommended on CLI; use WORKDAY_CLIENT_SECRET env var)")
    p.add_argument("--client-secret-file", help="Read client secret from a file")
    p.add_argument("--client-secret-stdin", action="store_true", help="Read client secret from stdin (pipe)")
    p.add_argument("--auth-url", default=DEFAULT_AUTH_URL)
    p.add_argument("--token-url", default=DEFAULT_TOKEN_URL)
    p.add_argument("--port", type=int, default=8000)
    p.add_argument("--redirect-path", default="/callback")
    p.add_argument("--scope", default="openid")
    p.add_argument("--state", default="state123")
    p.add_argument("--dry-run", action="store_true", help="Print the authorize URL and exit")
    p.add_argument("--no-open", action="store_true", help="Do not open the browser automatically")
    p.add_argument("--save", action="store_true", help="Save token response to token.json")
    args = p.parse_args(argv)

    client_id = args.client_id or os.getenv("WORKDAY_CLIENT_ID")
    client_secret = None
    # precedence: explicit arg > file > stdin > env var > interactive prompt
    if args.client_secret:
        client_secret = args.client_secret
    elif args.client_secret_file:
        try:
            with open(args.client_secret_file, "r", encoding="utf-8") as f:
                client_secret = f.read().strip()
        except Exception as exc:
            print("Failed to read client secret file:", exc)
            return 2
    elif args.client_secret_stdin:
        # read remaining stdin until EOF
        client_secret = sys.stdin.read().strip()
    else:
        client_secret = os.getenv("WORKDAY_CLIENT_SECRET")
    if not client_id:
        print("Client ID not provided. Use --client-id or WORKDAY_CLIENT_ID env var.")
        return 2

    redirect_uri = f"http://127.0.0.1:{args.port}{args.redirect_path}"
    auth_url = build_authorize_url(args.auth_url, client_id, redirect_uri, args.scope, args.state)

    print("Authorize URL:")
    print(auth_url)
    if args.dry_run:
        return 0

    if not args.no_open:
        webbrowser.open(auth_url)

    # Start local server to capture the redirect
    with HTTPServer(("127.0.0.1", args.port), CallbackHandler) as httpd:
        print("Waiting for authorization response on", redirect_uri)
        httpd.handle_request()  # handle single request
        code = getattr(httpd, "_auth_code", None)
        state = getattr(httpd, "_auth_state", None)

    if state != args.state:
        print("State mismatch; aborting")
        return 3
    if not code:
        print("No code received; aborting")
        return 4

    if not client_secret:
        # attempt to read interactively (safer to use env var)
        client_secret = input("Client secret: ")

    print("Exchanging code for token...")
    token = exchange_code(args.token_url, client_id, client_secret, code, redirect_uri)
    print(json.dumps(token, indent=2))
    if args.save:
        with open("token.json", "w") as f:
            json.dump(token, f)
        print("Saved token.json")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
