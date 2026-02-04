#!/usr/bin/env python3
"""Remote J-Quants MCP server with Streamable HTTP transport.

Uses J-Quants V2 API with x-api-key header authentication.
Deploy this as a web service to use J-Quants MCP from mobile or remote clients.
"""

import json
import os
from pathlib import Path
from typing import Any

import httpx
from dotenv import load_dotenv
from fastmcp import FastMCP

# Load .env from the project root
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

JQUANTS_BASE = "https://api.jquants.com/v2"

mcp_server = FastMCP("JQuants-Remote-MCP-server")


async def _make_request(url: str, timeout: int = 30) -> dict[str, Any]:
    """Make an authenticated request to the J-Quants V2 API."""
    api_key = os.environ.get("JQUANTS_API_KEY", "")
    if not api_key:
        return {"error": "JQUANTS_API_KEY is not set.", "status": "auth_error"}

    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            headers = {"x-api-key": api_key}
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
    response = await _make_request(f"{JQUANTS_BASE}/equities/master")
    if "error" in response:
        return json.dumps(response, ensure_ascii=False)

    matches = [
        r
        for r in response.get("data", [])
        if query.lower() in r.get("CoName", "").lower()
        or query.lower() in r.get("CoNameEn", "").lower()
    ][start_position : start_position + limit]

    return json.dumps({"data": matches}, ensure_ascii=False)


@mcp_server.tool()
async def get_daily_quotes(
    code: str,
    from_date: str,
    to_date: str,
    limit: int = 10,
    start_position: int = 0,
) -> str:
    """Retrieve daily stock price data for a specified stock code.

    Args:
        code: Stock code. Example: "72030" (Toyota)
        from_date: Start date in YYYYMMDD format. Example: "20260101"
        to_date: End date in YYYYMMDD format. Example: "20260204"
        limit: Maximum number of results. Defaults to 10.
        start_position: Starting position for pagination. Defaults to 0.
    """
    url = f"{JQUANTS_BASE}/equities/bars/daily?code={code}&from={from_date}&to={to_date}"
    response = await _make_request(url)
    if "error" in response:
        return json.dumps(response, ensure_ascii=False)

    quotes = response.get("data", [])[start_position : start_position + limit]
    return json.dumps({"data": quotes}, ensure_ascii=False)


@mcp_server.tool()
async def get_financial_statements(
    code: str,
    limit: int = 10,
    start_position: int = 0,
) -> str:
    """Retrieve financial summary for a specified stock code.

    Returns quarterly financial summaries and disclosure information.

    Args:
        code: Stock code. Example: "72030" (Toyota)
        limit: Maximum number of results. Defaults to 10.
        start_position: Starting position for pagination. Defaults to 0.
    """
    url = f"{JQUANTS_BASE}/fins/summary?code={code}"
    response = await _make_request(url)
    if "error" in response:
        return json.dumps(response, ensure_ascii=False)

    statements = [
        {k: v for k, v in r.items() if v != ""}
        for r in response.get("data", [])
    ][start_position : start_position + limit]

    return json.dumps({"data": statements}, ensure_ascii=False)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8000"))
    mcp_server.run(
        transport="http",
        host="0.0.0.0",
        port=port,
        path="/mcp",
    )
