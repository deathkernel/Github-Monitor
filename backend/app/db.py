from pathlib import Path
import sqlite3

from .settings import settings

DB_PATH = Path(settings.database_url.replace("sqlite:///", "", 1))
DB_PATH.parent.mkdir(parents=True, exist_ok=True)

SCHEMA = """
CREATE TABLE IF NOT EXISTS repositories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    github_id INTEGER NOT NULL UNIQUE,
    full_name TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    owner TEXT NOT NULL,
    description TEXT,
    language TEXT,
    visibility TEXT,
    private INTEGER NOT NULL DEFAULT 0,
    archived INTEGER NOT NULL DEFAULT 0,
    fork INTEGER NOT NULL DEFAULT 0,
    stars INTEGER NOT NULL DEFAULT 0,
    forks INTEGER NOT NULL DEFAULT 0,
    open_issues INTEGER NOT NULL DEFAULT 0,
    default_branch TEXT,
    updated_at_github TEXT,
    pushed_at_github TEXT,
    synced_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS ix_repositories_updated
ON repositories(updated_at_github);

CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_key TEXT NOT NULL UNIQUE,
    repo_full_name TEXT NOT NULL,
    event_type TEXT NOT NULL,
    title TEXT NOT NULL,
    actor TEXT,
    url TEXT,
    created_at TEXT NOT NULL,
    payload TEXT
);

CREATE INDEX IF NOT EXISTS ix_events_created
ON events(created_at);

CREATE INDEX IF NOT EXISTS ix_events_type
ON events(event_type);

CREATE TABLE IF NOT EXISTS sync_state (
    key TEXT PRIMARY KEY,
    value TEXT,
    updated_at TEXT NOT NULL
);
"""


def connect() -> sqlite3.Connection:
    db = sqlite3.connect(DB_PATH, check_same_thread=False)
    db.row_factory = sqlite3.Row
    db.executescript(SCHEMA)
    return db
