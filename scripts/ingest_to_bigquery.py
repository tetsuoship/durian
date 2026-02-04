#!/usr/bin/env python3
"""Fetch data from J-Quants V2 API and load into BigQuery.

Usage:
    python scripts/ingest_to_bigquery.py

Requires:
    - JQUANTS_API_KEY environment variable
    - GOOGLE_CLOUD_PROJECT environment variable (or gcloud default project)
    - google-cloud-bigquery and httpx packages
"""

import os
import sys
import json
from datetime import datetime, timedelta

import httpx
from google.cloud import bigquery

JQUANTS_BASE = "https://api.jquants.com/v2"
PROJECT_ID = os.environ.get("GOOGLE_CLOUD_PROJECT", "gen-lang-client-0620989837")
DATASET = "jquants"
API_KEY = os.environ.get("JQUANTS_API_KEY", "")


def make_request(url: str) -> dict:
    """Make an authenticated request to J-Quants V2 API."""
    headers = {"x-api-key": API_KEY}
    resp = httpx.get(url, headers=headers, timeout=60)
    if resp.status_code != 200:
        print(f"  ERROR: {resp.status_code} - {resp.text[:200]}")
        return {}
    return resp.json()


def fetch_all_pages(url: str) -> list:
    """Fetch all pages of paginated J-Quants API response."""
    all_data = []
    while url:
        resp = make_request(url)
        all_data.extend(resp.get("data", []))
        pagination_key = resp.get("pagination_key")
        if pagination_key:
            separator = "&" if "?" in url.split("#")[0] else "?"
            base_url = url.split("&pagination_key=")[0] if "&pagination_key=" in url else url
            url = f"{base_url}{separator}pagination_key={pagination_key}"
        else:
            break
    return all_data


def load_equities_master(client: bigquery.Client):
    """Fetch and load equities master data."""
    print("Fetching equities master...")
    data = fetch_all_pages(f"{JQUANTS_BASE}/equities/master")
    if not data:
        print("  No data returned.")
        return

    table_id = f"{PROJECT_ID}.{DATASET}.equities_master"

    # Truncate and reload (master data is a full snapshot)
    job_config = bigquery.LoadJobConfig(
        write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE,
        source_format=bigquery.SourceFormat.NEWLINE_DELIMITED_JSON,
        autodetect=False,
        schema=[
            bigquery.SchemaField("Date", "DATE"),
            bigquery.SchemaField("Code", "STRING"),
            bigquery.SchemaField("CoName", "STRING"),
            bigquery.SchemaField("CoNameEn", "STRING"),
            bigquery.SchemaField("S17", "STRING"),
            bigquery.SchemaField("S17Nm", "STRING"),
            bigquery.SchemaField("S33", "STRING"),
            bigquery.SchemaField("S33Nm", "STRING"),
            bigquery.SchemaField("ScaleCat", "STRING"),
            bigquery.SchemaField("Mkt", "STRING"),
            bigquery.SchemaField("MktNm", "STRING"),
            bigquery.SchemaField("Mrgn", "STRING"),
            bigquery.SchemaField("MrgnNm", "STRING"),
        ],
    )

    job = client.load_table_from_json(data, table_id, job_config=job_config)
    job.result()
    print(f"  Loaded {len(data)} rows into {table_id}")


def load_daily_bars(client: bigquery.Client, from_date: str, to_date: str):
    """Fetch and load daily bars for a date range."""
    print(f"Fetching daily bars ({from_date} to {to_date})...")
    url = f"{JQUANTS_BASE}/equities/bars/daily?from={from_date}&to={to_date}"
    data = fetch_all_pages(url)
    if not data:
        print("  No data returned.")
        return

    table_id = f"{PROJECT_ID}.{DATASET}.daily_bars"

    # Filter to schema fields only
    fields = ["Date", "Code", "O", "H", "L", "C", "Vo", "Va",
              "AdjFactor", "AdjO", "AdjH", "AdjL", "AdjC", "AdjVo"]
    filtered = [{k: row.get(k) for k in fields} for row in data]

    job_config = bigquery.LoadJobConfig(
        write_disposition=bigquery.WriteDisposition.WRITE_APPEND,
        source_format=bigquery.SourceFormat.NEWLINE_DELIMITED_JSON,
        schema=[
            bigquery.SchemaField("Date", "DATE"),
            bigquery.SchemaField("Code", "STRING"),
            bigquery.SchemaField("O", "FLOAT"),
            bigquery.SchemaField("H", "FLOAT"),
            bigquery.SchemaField("L", "FLOAT"),
            bigquery.SchemaField("C", "FLOAT"),
            bigquery.SchemaField("Vo", "FLOAT"),
            bigquery.SchemaField("Va", "FLOAT"),
            bigquery.SchemaField("AdjFactor", "FLOAT"),
            bigquery.SchemaField("AdjO", "FLOAT"),
            bigquery.SchemaField("AdjH", "FLOAT"),
            bigquery.SchemaField("AdjL", "FLOAT"),
            bigquery.SchemaField("AdjC", "FLOAT"),
            bigquery.SchemaField("AdjVo", "FLOAT"),
        ],
    )

    job = client.load_table_from_json(filtered, table_id, job_config=job_config)
    job.result()
    print(f"  Loaded {len(filtered)} rows into {table_id}")


def load_financial_summary(client: bigquery.Client):
    """Fetch and load financial summary data."""
    print("Fetching financial summary...")
    url = f"{JQUANTS_BASE}/fins/summary"
    data = fetch_all_pages(url)
    if not data:
        print("  No data returned.")
        return

    table_id = f"{PROJECT_ID}.{DATASET}.financial_summary"

    fields = ["DisclosedDate", "Code", "FiscalYear", "FiscalQuarter",
              "NetSales", "OperatingProfit", "OrdinaryProfit", "Profit",
              "EarningsPerShare", "TotalAssets", "Equity",
              "NumberOfIssuedAndOutstandingSharesAtTheEndOfFiscalYearIncludingTreasuryStock"]

    filtered = []
    for row in data:
        r = {}
        for k in fields:
            v = row.get(k, "")
            if k == "NumberOfIssuedAndOutstandingSharesAtTheEndOfFiscalYearIncludingTreasuryStock":
                r["NumberOfShares"] = float(v) if v != "" else None
            elif k in ("NetSales", "OperatingProfit", "OrdinaryProfit", "Profit",
                       "EarningsPerShare", "TotalAssets", "Equity"):
                r[k] = float(v) if v != "" else None
            else:
                r[k] = v if v != "" else None
        filtered.append(r)

    job_config = bigquery.LoadJobConfig(
        write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE,
        source_format=bigquery.SourceFormat.NEWLINE_DELIMITED_JSON,
        schema=[
            bigquery.SchemaField("DisclosedDate", "DATE"),
            bigquery.SchemaField("Code", "STRING"),
            bigquery.SchemaField("FiscalYear", "STRING"),
            bigquery.SchemaField("FiscalQuarter", "STRING"),
            bigquery.SchemaField("NetSales", "FLOAT"),
            bigquery.SchemaField("OperatingProfit", "FLOAT"),
            bigquery.SchemaField("OrdinaryProfit", "FLOAT"),
            bigquery.SchemaField("Profit", "FLOAT"),
            bigquery.SchemaField("EarningsPerShare", "FLOAT"),
            bigquery.SchemaField("TotalAssets", "FLOAT"),
            bigquery.SchemaField("Equity", "FLOAT"),
            bigquery.SchemaField("NumberOfShares", "FLOAT"),
        ],
    )

    job = client.load_table_from_json(filtered, table_id, job_config=job_config)
    job.result()
    print(f"  Loaded {len(filtered)} rows into {table_id}")


def main():
    if not API_KEY:
        print("ERROR: JQUANTS_API_KEY environment variable is not set.")
        sys.exit(1)

    client = bigquery.Client(project=PROJECT_ID)

    # Load equities master
    load_equities_master(client)

    # Load daily bars (last 30 days by default)
    to_date = datetime.now().strftime("%Y%m%d")
    from_date = (datetime.now() - timedelta(days=30)).strftime("%Y%m%d")
    load_daily_bars(client, from_date, to_date)

    # Load financial summary
    load_financial_summary(client)

    print("\nDone!")


if __name__ == "__main__":
    main()
