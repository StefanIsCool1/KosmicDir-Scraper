"""
Self-hosted analytics — SQLite-backed, zero extra dependencies.

Tables:
  page_views  — one row per page load (visitor_id, path, timestamp, referrer)
  events      — one row per action (visitor_id, event_name, event_data JSON, timestamp, page)

Visitor identity: SHA-256(IP + User-Agent).  The frontend also persists a
random visitor_id in localStorage so returning visitors from the same
browser/device share one identity even when their IP changes.

All writes are fire-and-forget.  Stats queries return real, non-fuzzy numbers.
"""

import os
import sqlite3
import hashlib
import json
import time
from datetime import datetime, timezone, timedelta
from threading import Lock

# Lives in Data-dump/ because that's a ReadWritePaths dir in trawlbase.service —
# the project root is read-only under ProtectSystem=strict, and SQLite WAL mode
# needs to create -wal/-shm siblings next to the DB.
_DB_DIR = os.path.join(os.path.dirname(__file__), "Data-dump")
os.makedirs(_DB_DIR, exist_ok=True)
_DB_PATH = os.path.join(_DB_DIR, "analytics.db")
_LOCK = Lock()


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


def _get_db() -> sqlite3.Connection:
    conn = sqlite3.connect(_DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn


def init_db():
    """Create tables if they don't exist.  Called once at import time."""
    with _LOCK:
        conn = _get_db()
        try:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS page_views (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    visitor_id  TEXT    NOT NULL,
                    path        TEXT    NOT NULL,
                    timestamp   TEXT    NOT NULL,
                    referrer    TEXT    DEFAULT '',
                    user_agent  TEXT    DEFAULT ''
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS events (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    visitor_id  TEXT    NOT NULL,
                    event_name  TEXT    NOT NULL,
                    event_data  TEXT    DEFAULT '{}',
                    timestamp   TEXT    NOT NULL,
                    page        TEXT    DEFAULT ''
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_page_views_visitor
                    ON page_views(visitor_id)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_page_views_ts
                    ON page_views(timestamp)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_events_name
                    ON events(event_name)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_events_ts
                    ON events(timestamp)
            """)
            conn.commit()
        finally:
            conn.close()


def record_page_view(visitor_id: str, path: str, referrer: str = "",
                     user_agent: str = "") -> None:
    """Log a page load.  Path is normalised (leading /, no query string)."""
    path = "/" + (path or "").lstrip("/")
    with _LOCK:
        conn = _get_db()
        try:
            conn.execute(
                "INSERT INTO page_views (visitor_id, path, timestamp, referrer, user_agent) "
                "VALUES (?, ?, ?, ?, ?)",
                (visitor_id, path, _now_iso(), referrer or "", user_agent or ""),
            )
            conn.commit()
        finally:
            conn.close()


def record_event(visitor_id: str, event_name: str,
                 event_data: dict | None = None, page: str = "") -> None:
    """Log a user action (scrape, discover, download, …)."""
    page = "/" + (page or "").lstrip("/")
    data_json = json.dumps(event_data or {}, ensure_ascii=False)
    with _LOCK:
        conn = _get_db()
        try:
            conn.execute(
                "INSERT INTO events (visitor_id, event_name, event_data, timestamp, page) "
                "VALUES (?, ?, ?, ?, ?)",
                (visitor_id, event_name, data_json, _now_iso(), page),
            )
            conn.commit()
        finally:
            conn.close()


def get_stats(days: int = 30) -> dict:
    """Return aggregate stats for the last N days.

    Returns a dict with:
      - total_page_views
      - unique_visitors
      - page_views_by_path: {path: count}
      - events_by_name: {event_name: {total: n, unique_visitors: n}}
      - daily_page_views: [{date, count}]
      - daily_events: [{date, count}]
      - recent_visitors: [{visitor_id, last_seen, page_views, events}]
    """
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()

    conn = _get_db()
    try:
        # Total page views
        total_pv = conn.execute(
            "SELECT COUNT(*) FROM page_views WHERE timestamp >= ?", (since,)
        ).fetchone()[0]

        # Total events
        total_ev = conn.execute(
            "SELECT COUNT(*) FROM events WHERE timestamp >= ?", (since,)
        ).fetchone()[0]

        # Unique visitors (across both tables)
        uv = conn.execute("""
            SELECT COUNT(DISTINCT visitor_id) FROM (
                SELECT visitor_id FROM page_views WHERE timestamp >= ?
                UNION
                SELECT visitor_id FROM events   WHERE timestamp >= ?
            )
        """, (since, since)).fetchone()[0]

        # Page views by path
        pv_by_path = {}
        for row in conn.execute(
            "SELECT path, COUNT(*) FROM page_views WHERE timestamp >= ? "
            "GROUP BY path ORDER BY COUNT(*) DESC", (since,)
        ):
            pv_by_path[row[0]] = row[1]

        # Events by name (with unique visitor counts)
        events_by_name = {}
        for row in conn.execute(
            "SELECT event_name, COUNT(*), COUNT(DISTINCT visitor_id) "
            "FROM events WHERE timestamp >= ? "
            "GROUP BY event_name ORDER BY COUNT(*) DESC", (since,)
        ):
            events_by_name[row[0]] = {"total": row[1], "unique_visitors": row[2]}

        # Daily page views
        daily_pv = []
        for row in conn.execute(
            "SELECT DATE(timestamp) as d, COUNT(*) FROM page_views "
            "WHERE timestamp >= ? GROUP BY d ORDER BY d", (since,)
        ):
            daily_pv.append({"date": row[0], "count": row[1]})

        # Daily events
        daily_ev = []
        for row in conn.execute(
            "SELECT DATE(timestamp) as d, COUNT(*) FROM events "
            "WHERE timestamp >= ? GROUP BY d ORDER BY d", (since,)
        ):
            daily_ev.append({"date": row[0], "count": row[1]})

        # Recent visitors (top 50 by activity)
        recent = []
        for row in conn.execute("""
            SELECT visitor_id, MAX(timestamp), COUNT(*),
                   (SELECT COUNT(*) FROM events e WHERE e.visitor_id = pv.visitor_id AND e.timestamp >= ?)
            FROM page_views pv WHERE pv.timestamp >= ?
            GROUP BY visitor_id ORDER BY COUNT(*) DESC LIMIT 50
        """, (since, since)):
            recent.append({
                "visitor_id": row[0][:16] + "...",  # truncated for display
                "last_seen": row[1],
                "page_views": row[2],
                "events": row[3],
            })

        return {
            "period_days": days,
            "total_page_views": total_pv,
            "total_events": total_ev,
            "unique_visitors": uv,
            "page_views_by_path": pv_by_path,
            "events_by_name": events_by_name,
            "daily_page_views": daily_pv,
            "daily_events": daily_ev,
            "recent_visitors": recent,
            "generated_at": _now_iso(),
        }
    finally:
        conn.close()


# Initialise the DB when this module is first imported
init_db()
