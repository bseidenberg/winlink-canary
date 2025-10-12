#!/usr/bin/env python3
"""
Poll multiple URLs for JSON health data, merge and render HTML.
Usage:
    python poll_health.py -u url1 url2 ... [-o output.html] [-i interval]
"""

import argparse
import json
import re
import sys
import time
import urllib.request
from html import escape
from datetime import datetime


def fetch_health(url):
    """Fetch and parse JSON from URL, handling <pre>...</pre> wrappers."""
    with urllib.request.urlopen(url, timeout=10) as resp:
        raw = resp.read().decode("utf-8", errors="replace")

    # Extract JSON inside <pre> tags if present
    match = re.search(r"<pre[^>]*>(.*?)</pre>", raw, re.S | re.I)
    if match:
        raw = match.group(1).strip()

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON from {url}: {e}")

    return data.get("health", [])


def ts_to_local(ts):
    """Convert UNIX timestamp to local time string."""
    if not ts:
        return ""
    try:
        return datetime.fromtimestamp(float(ts)).strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return ""


def render_html(health, failed_urls, refresh_interval):
    """Return HTML string representing the health table."""
    updated = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    html = [
        "<!DOCTYPE html>",
        "<html><head><meta charset='utf-8'>",
        "<title>System Health Summary</title>",
        f"<meta http-equiv='refresh' content='{refresh_interval}'>",
        "<style>",
        "body { font-family: sans-serif; margin: 20px; text-align: center; }",
        "h1 { margin-bottom: 10px; }",
        "h2 { margin-bottom: 10px; }",
        "div.table-container { display: inline-block; text-align: left; }",
        "table { border-collapse: collapse; width: auto; white-space: nowrap; }",
        "th, td { border: 1px solid #ccc; padding: 6px 10px; }",
        "th { background: #eee; }",
        "td:nth-child(1) { text-align: left; }",
        "td:nth-child(2), td:nth-child(3), td:nth-child(4) { text-align: center; }",
        ".ball { display: inline-block; width: 12px; height: 12px; border-radius: 50%; margin-right: 6px; }",
        ".green { background: #0a0; } .red { background: #c00; } .grey { background: #888; }",
        "p.failed { color: red; margin-top: 20px; text-align: left; }",
        "</style>",
        "<script>",
        "function showHistory(name, hist) {",
        "  const w = window.open('', '_blank', 'width=500,height=200');",
        "  w.document.write('<h3>'+name+'</h3><pre>'+hist+'</pre>');",
        "  w.document.close();",
        "}",
        "</script>",
        "</head><body>",
        f"<h1>Winlink Gateway Health Summary</h1>",
        f"<h2>(updated {updated})</h2>",
        "<div class='table-container'>",
        "<table>",
        "<tr><th>Name</th><th>Frequency (MHz)</th><th>Status</th><th>Last Healthy</th></tr>",
    ]

    for entry in health:
        name = escape(entry.get("name", ""))
        freq = entry.get("frequency", 0.0)
        state = entry.get("state", "UNKNOWN").upper()
        hist = escape(entry.get("history", ""))
        last_healthy = ts_to_local(entry.get("last_healthy"))

        if state == "HEALTHY":
            color = "green"
        elif state == "UNHEALTHY":
            color = "red"
        else:
            color = "grey"

        html.append(
            f"<tr>"
            f"<td>{name}</td>"
            f"<td>{freq:.3f}</td>"
            f"<td><span class='ball {color}'></span>"
            f"<a href='javascript:void(0)' onclick=\"showHistory('{name}','{hist}')\">{state}</a></td>"
            f"<td>{last_healthy}</td>"
            f"</tr>"
        )

    html.append("</table>")

    if failed_urls:
        html.append(f"<p class='failed'><strong>Failed to fetch status from {len(failed_urls)} URLs.</strong><br>")
        html.append("</p>")

    html.append("</div></body></html>")
    return "\n".join(html)


def main():
    parser = argparse.ArgumentParser(description="Poll URLs for JSON health data.")
    parser.add_argument(
        "-u", "--urls", nargs="+", required=True,
        help="List of URLs to poll (space-separated)."
    )
    parser.add_argument(
        "-o", "--output", help="Output HTML file. Defaults to stdout."
    )
    parser.add_argument(
        "-i", "--interval", type=int, default=0,
        help="Seconds between polls (0 to run once)."
    )
    args = parser.parse_args()

    while True:
        all_health = []
        failed = []

        for url in args.urls:
            try:
                all_health.extend(fetch_health(url))
            except Exception as e:
                sys.stderr.write(f"Failed to fetch {url}: {e}\n")
                failed.append(url)

        all_health.sort(key=lambda x: x.get("name", ""))

        html = render_html(all_health, failed, args.interval if args.interval > 0 else 0)

        if args.output:
            with open(args.output, "w", encoding="utf-8") as f:
                f.write(html)
        else:
            print(html)

        if args.interval <= 0:
            break

        time.sleep(args.interval)


if __name__ == "__main__":
    main()
