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
    response = await _make_request("https://api.jquants.com/v2/listed/info")
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
    url = f"https://api.jquants.com/v2/prices/daily_quotes?code={code}&from={from_date}&to={to_date}"
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
    url = f"https://api.jquants.com/v2/fins/statements?code={code}"
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
