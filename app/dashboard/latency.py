"""Present sparse latency evidence without filling gaps in monitoring records."""

from datetime import datetime


def latency_card(records: list[dict], assessed_at: str) -> dict:
    """Select the last measured minute and explicitly identify historical values."""
    now = datetime.fromisoformat(assessed_at)
    rows = sorted(records, key=lambda row: datetime.fromisoformat(row["timestamp"]))
    latest = rows[-1] if rows else {}
    measured = [row for row in rows if row.get("average_latency") is not None]
    if latest.get("request_count") == 0 and latest.get("average_latency") is None:
        reason = "No requests measured in the latest minute; latency is not applicable for that minute."
    elif latest.get("average_latency") is None:
        reason = "Latency is missing in the latest minute; collection may be delayed or incomplete."
    else:
        reason = "Measured mean request latency for the displayed minute."
    if not measured:
        return {"label": "Server latency (ms)", "value": "Not measured",
                "caption": reason + " No latency measurement is available in the selected window."}
    row = measured[-1]
    timestamp = datetime.fromisoformat(row["timestamp"])
    age = max(0, int((now - timestamp).total_seconds()))
    historical = row is not latest or age > 900
    freshness = "Historical measurement" if historical else "Latest measured minute"
    return {
        "label": "Last measured latency (ms)",
        "value": f"{row['average_latency']:,.2f}",
        "caption": (f"{freshness}: {timestamp.isoformat()} (age {age // 60}m {age % 60}s). "
                    + reason),
    }
