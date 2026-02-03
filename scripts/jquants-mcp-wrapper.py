#!/usr/bin/env python3
"""Wrapper script that obtains a J-Quants ID token from an API key
and launches jquants-free-mcp-server with the token set."""

import os
import subprocess
import sys
from pathlib import Path

import httpx
from dotenv import load_dotenv

# Load .env from the project root
load_dotenv(Path(__file__).resolve().parent.parent / ".env")


def get_id_token(api_key: str) -> str:
    """Obtain an ID token from the J-Quants API using the API key."""
    # Step 1: Get refresh token
    resp = httpx.post(
        "https://api.jquants.com/v1/token/auth_user",
        json={"apikey": api_key},
        timeout=30,
    )
    resp.raise_for_status()
    refresh_token = resp.json()["refreshToken"]

    # Step 2: Get ID token
    resp = httpx.post(
        f"https://api.jquants.com/v1/token/auth_refresh?refreshtoken={refresh_token}",
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()["idToken"]


def main() -> None:
    api_key = os.environ.get("JQUANTS_API_KEY", "")
    if not api_key:
        print("Error: JQUANTS_API_KEY is not set.", file=sys.stderr)
        sys.exit(1)

    try:
        id_token = get_id_token(api_key)
    except Exception as e:
        print(f"Error obtaining ID token: {e}", file=sys.stderr)
        sys.exit(1)

    env = os.environ.copy()
    env["JQUANTS_ID_TOKEN"] = id_token

    subprocess.run(["jquants-free-mcp-server"], env=env)


if __name__ == "__main__":
    main()
