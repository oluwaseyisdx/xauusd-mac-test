"""Read-only MQL5 FILE_COMMON CSV bridge for a native macOS Python process.

No broker credentials, no Python MetaTrader5 extension, no order methods.
Never use a snapshot as a trading signal without stale-data safeguards.
"""
import csv
import os
from pathlib import Path
from typing import Optional

FILENAME = "DUALBOT_TEST14_BRIDGE.csv"
REQUIRED_FIELDS = (
    "run_id", "seq", "terminal_connected", "demo_account",
    "quotes_available", "symbol", "bid", "ask", "tick_unix_seconds", "orders_sent",
)


def candidates(prefix: Path):
    """FILE_COMMON lives under the Wine user's MetaQuotes Terminal/Common/Files."""
    yield from prefix.glob(f"drive_c/users/*/AppData/Roaming/MetaQuotes/Terminal/Common/Files/{FILENAME}")
    yield from prefix.glob(f"drive_c/users/*/Application Data/MetaQuotes/Terminal/Common/Files/{FILENAME}")
    # Do not use a non-common MQL5/Files file: it would not prove FILE_COMMON.


def parse_snapshot(path: Path, expected_run_id: Optional[str] = None) -> dict:
    with open(path, "r", newline="", encoding="utf-8-sig") as fh:
        rows = list(csv.DictReader(fh, delimiter=";"))
    if len(rows) != 1:
        raise ValueError("Expected exactly one snapshot row")
    row = rows[0]
    if not all(key in row for key in REQUIRED_FIELDS):
        raise ValueError("Missing fields in snapshot")
    if expected_run_id is not None and row["run_id"] != expected_run_id:
        raise ValueError("Snapshot belongs to another workflow run")
    for key in ("seq", "terminal_connected", "demo_account", "quotes_available", "tick_unix_seconds", "orders_sent"):
        row[key] = int(row[key])
    for key in ("bid", "ask"):
        row[key] = float(row[key])
    if row["seq"] <= 0:
        raise ValueError("Snapshot sequence not positive")
    if row["orders_sent"] != 0:
        raise ValueError("Read-only safety check failed")
    if row["quotes_available"] and not (row["terminal_connected"] and 0 < row["bid"] < row["ask"]):
        raise ValueError("Invalid quote flags or spread")
    return row


def find_snapshot(prefix: Path, expected_run_id: str) -> dict:
    for path in candidates(prefix):
        if path.is_file():
            try:
                return parse_snapshot(path, expected_run_id)
            except (OSError, ValueError, UnicodeDecodeError):
                continue
    raise FileNotFoundError("No matching FILE_COMMON snapshot found")


def sanitized_report(snapshot: dict) -> dict:
    """No account IDs, server names or full quotes printed to public CI logs."""
    return {
        "bridge_file_seen": True,
        "run_id_matches": True,
        "heartbeat_seq": snapshot["seq"],
        "terminal_connected": bool(snapshot["terminal_connected"]),
        "demo_account": bool(snapshot["demo_account"]),
        "quotes_available": bool(snapshot["quotes_available"]),
        "symbol_nonempty": bool(snapshot["symbol"]),
        "orders_sent": snapshot["orders_sent"],
    }


if __name__ == "__main__":
    import json
    prefix = Path(os.environ["WINEPREFIX"])
    run_id = os.environ["BRIDGE_RUN_ID"]
    print(json.dumps(sanitized_report(find_snapshot(prefix, run_id)), sort_keys=True))
