#!/usr/bin/env python3
"""Script to subscribe Instagram webhook fields via Graph API."""

import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root / "src"))

import httpx
from ugc_bot.config import load_config


def subscribe_to_messages(page_id: str | None = None) -> None:
    """Subscribe to Instagram messages webhook field."""
    config = load_config()

    if not config.instagram.instagram_access_token:
        print("❌ Error: INSTAGRAM_ACCESS_TOKEN is not configured")
        print("   Set it in your .env file")
        sys.exit(1)

    # Use /me if page_id not provided
    endpoint = f"/me/subscribed_apps" if not page_id else f"/{page_id}/subscribed_apps"
    url = f"https://graph.instagram.com/v24.0{endpoint}"

    print(f"📡 Subscribing to Instagram webhook field 'messages'...")
    print(f"   Endpoint: {url}")
    print(f"   Page ID: {page_id or 'me (current user)'}")

    try:
        response = httpx.post(
            url,
            params={
                "subscribed_fields": "messages",
                "access_token": config.instagram.instagram_access_token,
            },
            timeout=30.0,
        )
        response.raise_for_status()
        result = response.json()

        if result.get("success"):
            print("✅ Successfully subscribed to 'messages' webhook field")
        else:
            print(f"⚠️  Response: {result}")
            if "error" in result:
                error = result["error"]
                print(f"❌ Error: {error.get('message', 'Unknown error')}")
                print(f"   Type: {error.get('type', 'Unknown')}")
                print(f"   Code: {error.get('code', 'Unknown')}")
                sys.exit(1)
    except httpx.HTTPStatusError as e:
        print(f"❌ HTTP Error: {e.response.status_code}")
        print(f"   Response: {e.response.text}")
        sys.exit(1)
    except httpx.RequestError as e:
        print(f"❌ Request Error: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"❌ Error: {e}")
        sys.exit(1)


def list_subscriptions(page_id: str | None = None) -> None:
    """List current webhook subscriptions."""
    config = load_config()

    if not config.instagram.instagram_access_token:
        print("❌ Error: INSTAGRAM_ACCESS_TOKEN is not configured")
        sys.exit(1)

    endpoint = f"/me/subscribed_apps" if not page_id else f"/{page_id}/subscribed_apps"
    url = f"https://graph.instagram.com/v24.0{endpoint}"

    print(f"📋 Listing current subscriptions...")
    print(f"   Endpoint: {url}")

    try:
        response = httpx.get(
            url,
            params={
                "access_token": config.instagram.instagram_access_token,
            },
            timeout=30.0,
        )
        response.raise_for_status()
        result = response.json()

        if "data" in result:
            subscriptions = result["data"]
            if subscriptions:
                print(f"✅ Found {len(subscriptions)} subscription(s):")
                for sub in subscriptions:
                    print(f"   - {sub}")
            else:
                print("⚠️  No subscriptions found")
        else:
            print(f"Response: {result}")
    except httpx.HTTPStatusError as e:
        print(f"❌ HTTP Error: {e.response.status_code}")
        print(f"   Response: {e.response.text}")
        sys.exit(1)
    except Exception as e:
        print(f"❌ Error: {e}")
        sys.exit(1)


def main() -> None:
    """Main entry point."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Subscribe to Instagram webhook fields"
    )
    parser.add_argument(
        "--page-id",
        type=str,
        help="Instagram Page ID (optional, uses /me if not provided)",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="List current subscriptions instead of subscribing",
    )
    args = parser.parse_args()

    if args.list:
        list_subscriptions(args.page_id)
    else:
        subscribe_to_messages(args.page_id)


if __name__ == "__main__":
    main()
