#!/usr/bin/env python3
"""
Garmin OAuth Authentication via Browser Login.

Bypasses the 429-blocked SSO programmatic login endpoint by using a real
Chromium browser (Playwright) to complete the login, then exchanges the
resulting SSO ticket for garth-compatible OAuth1 + OAuth2 tokens.

Tokens are saved per-user to data/garmin_tokens/<user_id>/ and reused
automatically by garmin_tools.py (valid ~6 months).

Usage:
    python scripts/garmin_browser_auth.py --user <user_id>

First-time Playwright setup (installs Chromium — run once):
    python -m playwright install chromium
"""

import argparse
import json
import re
import sys
import time
from pathlib import Path
from urllib.parse import parse_qs

import requests
from requests_oauthlib import OAuth1Session
from playwright.sync_api import sync_playwright

# ── Project root on sys.path so we can import config ─────────────────────────
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import DATA_DIR  # noqa: E402

TOKEN_BASE = DATA_DIR / "garmin_tokens"

OAUTH_CONSUMER_URL = "https://thegarth.s3.amazonaws.com/oauth_consumer.json"
ANDROID_UA = "com.garmin.android.apps.connectmobile"


# ── Auth steps ────────────────────────────────────────────────────────────────

def get_oauth_consumer() -> dict:
    """Fetch shared OAuth consumer key/secret from garth's S3 bucket."""
    resp = requests.get(OAUTH_CONSUMER_URL, timeout=10)
    resp.raise_for_status()
    return resp.json()


def browser_login() -> str:
    """Open a real Chromium browser, let the user log in, return the SSO ticket."""
    ticket = None
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        page = browser.new_page()

        sso_url = (
            "https://sso.garmin.com/sso/embed"
            "?id=gauth-widget"
            "&embedWidget=true"
            "&gauthHost=https://sso.garmin.com/sso"
            "&clientId=GarminConnect"
            "&locale=en_US"
            "&redirectAfterAccountLoginUrl=https://sso.garmin.com/sso/embed"
            "&service=https://sso.garmin.com/sso/embed"
        )
        page.goto(sso_url)

        print()
        print("=" * 52)
        print("  Browser opened — log in with your Garmin")
        print("  credentials. The window closes automatically")
        print("  after a successful login.")
        print("=" * 52)
        print()

        deadline = time.time() + 300  # 5-minute timeout
        while time.time() < deadline:
            try:
                # Check page content for the SSO ticket
                for source in (page.url, page.content()):
                    m = re.search(r"ticket=(ST-[A-Za-z0-9\-]+)", source)
                    if m:
                        ticket = m.group(1)
                        print(f"  Ticket captured: {ticket[:30]}...")
                        break
            except Exception:
                pass

            if ticket:
                break
            page.wait_for_timeout(500)

        browser.close()

    if not ticket:
        print("ERROR: Timed out waiting for login (5 min). Run the script again.")
        sys.exit(1)

    return ticket


def exchange_oauth1(ticket: str, consumer: dict) -> dict:
    """Exchange an SSO ticket for an OAuth1 token."""
    sess = OAuth1Session(consumer["consumer_key"], consumer["consumer_secret"])
    url = (
        f"https://connectapi.garmin.com/oauth-service/oauth/"
        f"preauthorized?ticket={ticket}"
        f"&login-url=https://sso.garmin.com/sso/embed"
        f"&accepts-mfa-tokens=true"
    )
    resp = sess.get(url, headers={"User-Agent": ANDROID_UA}, timeout=15)
    resp.raise_for_status()
    token = {k: v[0] for k, v in parse_qs(resp.text).items()}
    token["domain"] = "garmin.com"
    return token


def exchange_oauth2(oauth1: dict, consumer: dict) -> dict:
    """Exchange OAuth1 token for OAuth2 token."""
    sess = OAuth1Session(
        consumer["consumer_key"],
        consumer["consumer_secret"],
        resource_owner_key=oauth1["oauth_token"],
        resource_owner_secret=oauth1["oauth_token_secret"],
    )
    data = {}
    if oauth1.get("mfa_token"):
        data["mfa_token"] = oauth1["mfa_token"]

    resp = sess.post(
        "https://connectapi.garmin.com/oauth-service/oauth/exchange/user/2.0",
        headers={
            "User-Agent": ANDROID_UA,
            "Content-Type": "application/x-www-form-urlencoded",
        },
        data=data,
        timeout=15,
    )
    resp.raise_for_status()
    token = resp.json()
    token["expires_at"] = int(time.time() + token["expires_in"])
    token["refresh_token_expires_at"] = int(time.time() + token["refresh_token_expires_in"])
    return token


def verify_tokens(oauth2: dict) -> str:
    """Call a lightweight Garmin API endpoint to confirm the tokens work."""
    resp = requests.get(
        "https://connectapi.garmin.com/userprofile-service/socialProfile",
        headers={
            "User-Agent": "GCM-iOS-5.7.2.1",
            "Authorization": f"Bearer {oauth2['access_token']}",
        },
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json().get("displayName", "unknown")


def save_tokens(oauth1: dict, oauth2: dict, user_id: str) -> Path:
    """Save tokens to a per-user directory in garth-compatible format."""
    store = TOKEN_BASE / user_id
    store.mkdir(parents=True, exist_ok=True)
    (store / "oauth1_token.json").write_text(json.dumps(oauth1, indent=2))
    (store / "oauth2_token.json").write_text(json.dumps(oauth2, indent=2))
    print(f"  Tokens saved to {store}")
    return store


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Garmin OAuth Browser Auth — generates per-user tokens."
    )
    parser.add_argument(
        "--user",
        required=True,
        help="User ID to associate the tokens with (e.g. Telegram user ID or username).",
    )
    args = parser.parse_args()
    user_id = args.user.strip()

    print("Garmin Browser Auth")
    print("=" * 52)
    print(f"  User: {user_id}")
    print("=" * 52)

    print("1/4  Fetching OAuth consumer credentials...")
    consumer = get_oauth_consumer()

    print("2/4  Launching browser for login...")
    ticket = browser_login()

    print("3/4  Exchanging ticket for OAuth tokens...")
    oauth1 = exchange_oauth1(ticket, consumer)
    print(f"     OAuth1 token: {oauth1['oauth_token'][:20]}...")
    oauth2 = exchange_oauth2(oauth1, consumer)
    print(f"     OAuth2 token: {oauth2['access_token'][:20]}...")

    print("4/4  Verifying tokens...")
    display_name = verify_tokens(oauth2)
    print(f"     Authenticated as: {display_name}")

    store = save_tokens(oauth1, oauth2, user_id)

    print()
    print("=" * 52)
    print(f"  Done! Tokens for user '{user_id}' saved to:")
    print(f"  {store}")
    print("=" * 52)


if __name__ == "__main__":
    main()
