"""Construct old schemas explicitly; never label a partial V2 database as V1."""
from pathlib import Path
import sqlite3


def remove_event_schema(conn: sqlite3.Connection) -> None:
    for row in conn.execute("SELECT name FROM sqlite_master WHERE type='trigger' AND name LIKE 'event_%'").fetchall():
        conn.execute(f'DROP TRIGGER "{row[0]}"')
    for name in ("automation_event_replays", "automation_event_routes", "automation_event_history",
                 "automation_event_processing", "automation_event_dedupe", "automation_event_ledger",
                 "automation_sync_checkpoints", "automation_usage_daily"):
        conn.execute(f'DROP TABLE IF EXISTS "{name}"')


def make_v1(path: Path) -> None:
    with sqlite3.connect(path) as conn:
        conn.executescript((Path(__file__).parent / "fixtures/phase3-v1-schema.sql").read_text())
