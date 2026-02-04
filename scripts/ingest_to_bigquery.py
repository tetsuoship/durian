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
    """Fetch and load daily bars for a date range (by date)."""
    print(f"Fetching daily bars ({from_date} to {to_date})...")

    table_id = f"{PROJECT_ID}.{DATASET}.daily_bars"
    fields = ["Date", "Code", "O", "H", "L", "C", "Vo", "Va",
              "AdjFactor", "AdjO", "AdjH", "AdjL", "AdjC", "AdjVo"]
    schema = [
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
    ]

    start = datetime.strptime(from_date, "%Y%m%d")
    end = datetime.strptime(to_date, "%Y%m%d")
    total_rows = 0

    current = start
    while current <= end:
        date_str = current.strftime("%Y%m%d")
        # Skip weekends
        if current.weekday() < 5:
            data = fetch_all_pages(f"{JQUANTS_BASE}/equities/bars/daily?date={date_str}")
            if data:
                filtered = [{k: row.get(k) for k in fields} for row in data]
                job_config = bigquery.LoadJobConfig(
                    write_disposition=bigquery.WriteDisposition.WRITE_APPEND,
                    source_format=bigquery.SourceFormat.NEWLINE_DELIMITED_JSON,
                    schema=schema,
                )
                job = client.load_table_from_json(filtered, table_id, job_config=job_config)
                job.result()
                total_rows += len(filtered)
                print(f"  {date_str}: {len(filtered)} rows")
        current += timedelta(days=1)

    print(f"  Total: {total_rows} rows loaded into {table_id}")


def load_financial_summary(client: bigquery.Client, from_date: str, to_date: str):
    """Fetch and load financial summary data by date."""
    print(f"Fetching financial summary ({from_date} to {to_date})...")

    table_id = f"{PROJECT_ID}.{DATASET}.financial_summary"
    schema = [
        bigquery.SchemaField("DiscDate", "DATE"),
        bigquery.SchemaField("Code", "STRING"),
        bigquery.SchemaField("DocType", "STRING"),
        bigquery.SchemaField("CurPerType", "STRING"),
        bigquery.SchemaField("CurFYEn", "STRING"),
        bigquery.SchemaField("Sales", "FLOAT"),
        bigquery.SchemaField("OP", "FLOAT"),
        bigquery.SchemaField("OdP", "FLOAT"),
        bigquery.SchemaField("NP", "FLOAT"),
        bigquery.SchemaField("EPS", "FLOAT"),
        bigquery.SchemaField("TA", "FLOAT"),
        bigquery.SchemaField("Eq", "FLOAT"),
    ]
    numeric_fields = {"Sales", "OP", "OdP", "NP", "EPS", "TA", "Eq"}
    string_fields = {"Code", "DocType", "CurPerType", "CurFYEn"}

    start = datetime.strptime(from_date, "%Y%m%d")
    end = datetime.strptime(to_date, "%Y%m%d")
    total_rows = 0

    current = start
    while current <= end:
        date_str = current.strftime("%Y%m%d")
        if current.weekday() < 5:
            data = fetch_all_pages(f"{JQUANTS_BASE}/fins/summary?date={date_str}")
            if data:
                filtered = []
                for row in data:
                    r = {}
                    r["DiscDate"] = row.get("DiscDate") or None
                    for k in string_fields:
                        r[k] = row.get(k) or None
                    for k in numeric_fields:
                        v = row.get(k, "")
                        r[k] = float(v) if v != "" else None
                    filtered.append(r)

                job_config = bigquery.LoadJobConfig(
                    write_disposition=bigquery.WriteDisposition.WRITE_APPEND,
                    source_format=bigquery.SourceFormat.NEWLINE_DELIMITED_JSON,
                    schema=schema,
                )
                job = client.load_table_from_json(filtered, table_id, job_config=job_config)
                job.result()
                total_rows += len(filtered)
                print(f"  {date_str}: {len(filtered)} rows")
        current += timedelta(days=1)

    print(f"  Total: {total_rows} rows loaded into {table_id}")


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

    # Load financial summary (same date range)
    load_financial_summary(client, from_date, to_date)

    print("\nDone!")


if __name__ == "__main__":
    main()
