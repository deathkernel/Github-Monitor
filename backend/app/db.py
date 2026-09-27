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

CREATE TABLE IF NOT EXISTS repository_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    github_id INTEGER NOT NULL,
    full_name TEXT NOT NULL,
    captured_at TEXT NOT NULL,
    stars INTEGER NOT NULL DEFAULT 0,
    forks INTEGER NOT NULL DEFAULT 0,
    open_issues INTEGER NOT NULL DEFAULT 0,
    pushed_at_github TEXT,
    archived INTEGER NOT NULL DEFAULT 0,
    private INTEGER NOT NULL DEFAULT 0,
    language TEXT
);

CREATE INDEX IF NOT EXISTS ix_repo_history_repo_time
ON repository_history(full_name, captured_at);

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

CREATE TABLE IF NOT EXISTS changes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    change_key TEXT NOT NULL UNIQUE,
    repo_full_name TEXT NOT NULL,
    change_type TEXT NOT NULL,
    field TEXT,
    before_value TEXT,
    after_value TEXT,
    severity TEXT NOT NULL DEFAULT 'info',
    detected_at TEXT NOT NULL,
    acknowledged INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS ix_changes_detected
ON changes(detected_at);

CREATE INDEX IF NOT EXISTS ix_changes_repo
ON changes(repo_full_name);

CREATE TABLE IF NOT EXISTS alerts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    alert_key TEXT NOT NULL UNIQUE,
    repo_full_name TEXT,
    rule TEXT NOT NULL,
    severity TEXT NOT NULL,
    title TEXT NOT NULL,
    details TEXT,
    status TEXT NOT NULL DEFAULT 'open',
    created_at TEXT NOT NULL,
    resolved_at TEXT
);

CREATE INDEX IF NOT EXISTS ix_alerts_status_time
ON alerts(status, created_at);

CREATE TABLE IF NOT EXISTS notification_deliveries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    alert_id INTEGER,
    channel TEXT NOT NULL,
    status TEXT NOT NULL,
    response_code INTEGER,
    error TEXT,
    delivered_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kind TEXT NOT NULL,
    payload TEXT,
    status TEXT NOT NULL DEFAULT 'queued',
    attempts INTEGER NOT NULL DEFAULT 0,
    run_after TEXT NOT NULL,
    created_at TEXT NOT NULL,
    started_at TEXT,
    finished_at TEXT,
    last_error TEXT
);

CREATE INDEX IF NOT EXISTS ix_jobs_queue
ON jobs(status, run_after);

CREATE TABLE IF NOT EXISTS action_audit (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    action TEXT NOT NULL,
    repo_full_name TEXT,
    target TEXT,
    status TEXT NOT NULL,
    detail TEXT,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS ix_action_audit_time
ON action_audit(created_at);

CREATE TABLE IF NOT EXISTS sync_state (
    key TEXT PRIMARY KEY,
    value TEXT,
    updated_at TEXT NOT NULL
);
"""


def connect() -> sqlite3.Connection:
    db = sqlite3.connect(DB_PATH, check_same_thread=False)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("PRAGMA busy_timeout=5000")
    db.executescript(SCHEMA)
    return db
