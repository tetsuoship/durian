#!/usr/bin/env python3
"""Send Slack alerts for significant stock movements.

Usage:
    python scripts/slack_alerts.py

Requires:
    - SLACK_WEBHOOK_URL environment variable
    - google-cloud-bigquery package
"""

import os
import sys
from datetime import datetime

import httpx
from google.cloud import bigquery

PROJECT_ID = os.environ.get("GOOGLE_CLOUD_PROJECT", "gen-lang-client-0620989837")
DATASET = "jquants"
SLACK_WEBHOOK_URL = os.environ.get("SLACK_WEBHOOK_URL", "")

# Alert thresholds
PRICE_CHANGE_THRESHOLD = 5.0  # Alert if price changed more than ±5%
VOLUME_SPIKE_THRESHOLD = 2.0  # Alert if volume is 2x average


def send_slack_message(text: str, blocks: list = None):
    """Send a message to Slack."""
    payload = {"text": text}
    if blocks:
        payload["blocks"] = blocks

    resp = httpx.post(SLACK_WEBHOOK_URL, json=payload, timeout=30)
    if resp.status_code != 200:
        print(f"Slack error: {resp.status_code} - {resp.text}")
        return False
    return True


def get_big_movers(client: bigquery.Client) -> list:
    """Find stocks with significant price changes."""
    query = """
    WITH latest_dates AS (
        SELECT DISTINCT Date
        FROM `{project}.{dataset}.daily_bars`
        ORDER BY Date DESC
        LIMIT 2
    ),
    today_data AS (
        SELECT Code, AdjC as Close, Vo as Volume, Date
        FROM `{project}.{dataset}.daily_bars`
        WHERE Date = (SELECT MAX(Date) FROM latest_dates)
    ),
    yesterday_data AS (
        SELECT Code, AdjC as Close, Vo as Volume
        FROM `{project}.{dataset}.daily_bars`
        WHERE Date = (SELECT MIN(Date) FROM latest_dates)
    ),
    avg_volume AS (
        SELECT Code, AVG(Vo) as AvgVolume
        FROM `{project}.{dataset}.daily_bars`
        WHERE Date >= DATE_SUB((SELECT MAX(Date) FROM latest_dates), INTERVAL 20 DAY)
        GROUP BY Code
    )
    SELECT
        t.Code,
        m.CoName,
        t.Close,
        y.Close as PrevClose,
        ROUND((t.Close - y.Close) / y.Close * 100, 2) as ChangePercent,
        t.Volume,
        a.AvgVolume,
        ROUND(t.Volume / NULLIF(a.AvgVolume, 0), 2) as VolumeRatio,
        t.Date
    FROM today_data t
    JOIN yesterday_data y ON t.Code = y.Code
    JOIN avg_volume a ON t.Code = a.Code
    JOIN `{project}.{dataset}.equities_master` m ON t.Code = m.Code
    WHERE y.Close > 0 AND a.AvgVolume > 0
    AND (
        ABS((t.Close - y.Close) / y.Close * 100) >= {price_threshold}
        OR t.Volume / a.AvgVolume >= {volume_threshold}
    )
    ORDER BY ABS((t.Close - y.Close) / y.Close * 100) DESC
    LIMIT 30
    """.format(
        project=PROJECT_ID,
        dataset=DATASET,
        price_threshold=PRICE_CHANGE_THRESHOLD,
        volume_threshold=VOLUME_SPIKE_THRESHOLD,
    )

    job = client.query(query)
    return list(job.result())


def format_alert_message(movers: list) -> tuple:
    """Format the alert message for Slack."""
    if not movers:
        return None, None

    date_str = movers[0].Date.strftime("%Y/%m/%d") if movers else datetime.now().strftime("%Y/%m/%d")

    # Separate gainers and losers
    gainers = [m for m in movers if m.ChangePercent >= PRICE_CHANGE_THRESHOLD]
    losers = [m for m in movers if m.ChangePercent <= -PRICE_CHANGE_THRESHOLD]
    volume_spikes = [m for m in movers if abs(m.ChangePercent) < PRICE_CHANGE_THRESHOLD and m.VolumeRatio >= VOLUME_SPIKE_THRESHOLD]

    blocks = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": f"J-Quants Alert ({date_str})"}
        }
    ]

    # Gainers
    if gainers:
        gainer_text = "\n".join([
            f"*{m.Code}* {m.CoName}: +{m.ChangePercent}% ({m.Close:,.0f}円)"
            for m in gainers[:10]
        ])
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": f":chart_with_upwards_trend: *急騰*\n{gainer_text}"}
        })

    # Losers
    if losers:
        loser_text = "\n".join([
            f"*{m.Code}* {m.CoName}: {m.ChangePercent}% ({m.Close:,.0f}円)"
            for m in losers[:10]
        ])
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": f":chart_with_downwards_trend: *急落*\n{loser_text}"}
        })

    # Volume spikes
    if volume_spikes:
        volume_text = "\n".join([
            f"*{m.Code}* {m.CoName}: 出来高{m.VolumeRatio}倍 ({m.ChangePercent:+.1f}%)"
            for m in volume_spikes[:10]
        ])
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": f":fire: *出来高急増*\n{volume_text}"}
        })

    summary = f"急騰{len(gainers)}件, 急落{len(losers)}件, 出来高急増{len(volume_spikes)}件"
    return summary, blocks


def main():
    if not SLACK_WEBHOOK_URL:
        print("ERROR: SLACK_WEBHOOK_URL environment variable is not set.")
        sys.exit(1)

    print("Checking for significant stock movements...")
    client = bigquery.Client(project=PROJECT_ID)

    movers = get_big_movers(client)
    print(f"Found {len(movers)} stocks with significant movements")

    if not movers:
        print("No significant movements today. Skipping Slack notification.")
        return

    summary, blocks = format_alert_message(movers)

    print(f"Sending Slack alert: {summary}")
    if send_slack_message(summary, blocks):
        print("Slack alert sent successfully!")
    else:
        print("Failed to send Slack alert")
        sys.exit(1)


if __name__ == "__main__":
    main()
