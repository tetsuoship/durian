#!/usr/bin/env python3
"""Remote J-Quants MCP server with Streamable HTTP transport.

Automatically handles API key -> ID token authentication and token refresh.
Deploy this as a web service to use J-Quants MCP from mobile or remote clients.
"""

import json
import os
import time
from pathlib import Path
from typing import Any

import httpx
from dotenv import load_dotenv
from fastmcp import FastMCP

# Load .env from the project root
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

mcp_server = FastMCP("JQuants-Remote-MCP-server")

# Token cache
_token_cache: dict[str, Any] = {"id_token": "", "expires_at": 0.0}


async def _refresh_id_token() -> str:
    """Obtain a fresh ID token from the J-Quants API.

    Supports two auth methods:
      - JQUANTS_REFRESH_TOKEN: Use refresh token directly (V1 accounts)
      - JQUANTS_API_KEY: Use API key to get refresh token first (V2 accounts)
    """
    refresh_token = os.environ.get("JQUANTS_REFRESH_TOKEN", "")
    api_key = os.environ.get("JQUANTS_API_KEY", "")

    async with httpx.AsyncClient(timeout=30) as client:
        if not refresh_token:
            if not api_key:
                raise RuntimeError(
                    "JQUANTS_REFRESH_TOKEN or JQUANTS_API_KEY must be set."
                )
            # API key -> refresh token (V2)
            resp = await client.post(
                "https://api.jquants.com/v1/token/auth_user",
                json={"apikey": api_key},
            )
            resp.raise_for_status()
            refresh_token = resp.json()["refreshToken"]

        # refresh token -> ID token
        resp = await client.post(
            f"https://api.jquants.com/v1/token/auth_refresh?refreshtoken={refresh_token}",
        )
        resp.raise_for_status()
        return resp.json()["idToken"]


async def _get_id_token() -> str:
    """Return a cached ID token, refreshing if expired (23h TTL)."""
    now = time.time()
    if _token_cache["id_token"] and now < _token_cache["expires_at"]:
        return _token_cache["id_token"]

    token = await _refresh_id_token()
    _token_cache["id_token"] = token
    _token_cache["expires_at"] = now + 23 * 3600  # 23 hours
    return token


async def _make_request(url: str, timeout: int = 30) -> dict[str, Any]:
    """Make an authenticated request to the J-Quants API."""
    try:
        id_token = await _get_id_token()
    except Exception as e:
        return {"error": f"認証エラー: {e}", "status": "auth_error"}

    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            headers = {"Authorization": f"Bearer {id_token}"}
            response = await client.get(url, headers=headers)
            if response.status_code != 200:
                return {
                    "error": f"APIリクエストに失敗しました。ステータスコード: {response.status_code}",
                    "status": "request_error",
                }
            return response.json()
    except httpx.TimeoutException:
        return {"error": f"タイムアウト({timeout}秒)", "status": "timeout"}
    except httpx.ConnectError:
        return {"error": "J-Quants APIへの接続に失敗しました。", "status": "connection_error"}
    except Exception as e:
        return {"error": str(e), "status": "unexpected_error"}


@mcp_server.tool()
async def search_company(
    query: str,
    limit: int = 10,
    start_position: int = 0,
) -> str:
    """Search for listed stocks by company name.

    Args:
        query: Company name search string (Japanese supported). Example: "トヨタ"
        limit: Maximum number of results. Defaults to 10.
        start_position: Starting position for pagination. Defaults to 0.
    """
    response = await _make_request("https://api.jquants.com/v1/listed/info")
    if "error" in response:
        return json.dumps(response, ensure_ascii=False)

    matches = [
        r
        for r in response.get("info", [])
        if query.lower() in r.get("CompanyName", "").lower()
        or query.lower() in r.get("CompanyNameEnglish", "").lower()
    ][start_position : start_position + limit]

    return json.dumps({"info": matches}, ensure_ascii=False)


@mcp_server.tool()
async def get_daily_quotes(
    code: str,
    from_date: str,
    to_date: str,
    limit: int = 10,
    start_position: int = 0,
) -> str:
    """Retrieve daily stock price data for a specified stock code.

    Data is available from 2 years prior to today up until 12 weeks ago.

    Args:
        code: Stock code. Example: "72030" (Toyota)
        from_date: Start date in YYYY-MM-DD format.
        to_date: End date in YYYY-MM-DD format.
        limit: Maximum number of results. Defaults to 10.
        start_position: Starting position for pagination. Defaults to 0.
    """
    url = f"https://api.jquants.com/v1/prices/daily_quotes?code={code}&from={from_date}&to={to_date}"
    response = await _make_request(url)
    if "error" in response:
        return json.dumps(response, ensure_ascii=False)

    quotes = response.get("daily_quotes", [])[start_position : start_position + limit]
    return json.dumps({"daily_quotes": quotes}, ensure_ascii=False)


@mcp_server.tool()
async def get_financial_statements(
    code: str,
    limit: int = 10,
    start_position: int = 0,
) -> str:
    """Retrieve financial statements for a specified stock code.

    Data is available from 2 years prior to today up until 12 weeks ago.
    Returns quarterly financial summaries and disclosure information.

    Args:
        code: Stock code. Example: "72030" (Toyota)
        limit: Maximum number of results. Defaults to 10.
        start_position: Starting position for pagination. Defaults to 0.
    """
    url = f"https://api.jquants.com/v1/fins/statements?code={code}"
    response = await _make_request(url)
    if "error" in response:
        return json.dumps(response, ensure_ascii=False)

    statements = [
        {k: v for k, v in r.items() if v != ""}
        for r in response.get("statements", [])
    ][start_position : start_position + limit]

    return json.dumps({"statements": statements}, ensure_ascii=False)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8000"))
    mcp_server.run(
        transport="http",
        host="0.0.0.0",
        port=port,
        path="/mcp",
    )
