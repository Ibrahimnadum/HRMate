"""SQLite storage with numbered migrations (PRAGMA user_version)."""
import json
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime

from . import config

V2 = """
CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);

CREATE TABLE departments (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE COLLATE NOCASE,
    legacy_id INTEGER
);

CREATE TABLE employees (
    id INTEGER PRIMARY KEY,
    badge TEXT NOT NULL UNIQUE,            -- the user ID on the devices
    name TEXT NOT NULL DEFAULT '',
    department_id INTEGER REFERENCES departments(id) ON DELETE SET NULL,
    title TEXT NOT NULL DEFAULT '',
    gender TEXT NOT NULL DEFAULT '',
    card TEXT NOT NULL DEFAULT '',
    active INTEGER NOT NULL DEFAULT 1,
    note TEXT NOT NULL DEFAULT '',
    device_name TEXT NOT NULL DEFAULT '',  -- name as stored on the devices
    legacy_id INTEGER,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE devices (
    id INTEGER PRIMARY KEY,
    serial TEXT UNIQUE,
    name TEXT NOT NULL,
    ip TEXT,
    port INTEGER NOT NULL DEFAULT 4370,
    commkey INTEGER NOT NULL DEFAULT 0,
    model TEXT NOT NULL DEFAULT '',
    location TEXT NOT NULL DEFAULT '',
    active INTEGER NOT NULL DEFAULT 1,     -- polled
    retired INTEGER NOT NULL DEFAULT 0,    -- kept only for its history
    firmware TEXT,
    online INTEGER,
    fail_count INTEGER NOT NULL DEFAULT 0,
    status_since TEXT,
    last_check_at TEXT,
    last_pull_at TEXT,
    last_pull_try TEXT,
    last_error TEXT,
    records_on_device INTEGER,
    users_on_device INTEGER,
    device_time_offset INTEGER             -- seconds the device clock is ahead of the server
);

CREATE TABLE punches (
    id INTEGER PRIMARY KEY,
    badge TEXT NOT NULL,
    ts TEXT NOT NULL,                      -- local time 'YYYY-MM-DD HH:MM:SS'
    device_id INTEGER REFERENCES devices(id),
    source TEXT NOT NULL,                  -- device | legacy | manual
    verify INTEGER,
    state INTEGER,
    note TEXT,
    created_by TEXT,
    created_at TEXT,
    UNIQUE (device_id, badge, ts)
);
CREATE INDEX punches_ts ON punches(ts);
CREATE INDEX punches_badge_ts ON punches(badge, ts);

CREATE TABLE events (
    id INTEGER PRIMARY KEY,
    device_id INTEGER REFERENCES devices(id),
    ts TEXT NOT NULL,
    kind TEXT NOT NULL,
    detail TEXT
);
CREATE INDEX events_ts ON events(ts);

CREATE TABLE accounts (
    username TEXT PRIMARY KEY,
    pw_hash TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'hr',       -- admin | hr | viewer
    display_name TEXT NOT NULL DEFAULT '',
    failed INTEGER NOT NULL DEFAULT 0,
    locked_until TEXT,
    last_login TEXT,
    created_at TEXT
);

CREATE TABLE audit (
    id INTEGER PRIMARY KEY,
    ts TEXT NOT NULL,
    username TEXT,
    action TEXT NOT NULL,
    target TEXT,
    detail TEXT
);
CREATE INDEX audit_ts ON audit(ts);
"""

V3 = """
ALTER TABLE employees ADD COLUMN emp_no TEXT NOT NULL DEFAULT '';   -- HR's real employee number
ALTER TABLE employees ADD COLUMN phone TEXT NOT NULL DEFAULT '';
CREATE INDEX employees_emp_no ON employees(emp_no);
"""

V4 = """
CREATE TABLE device_users (                 -- what each device holds, from the last scan
    device_id INTEGER NOT NULL REFERENCES devices(id) ON DELETE CASCADE,
    badge TEXT NOT NULL,
    uid INTEGER NOT NULL,                   -- the device's internal slot
    name TEXT NOT NULL DEFAULT '',
    privilege INTEGER NOT NULL DEFAULT 0,
    card TEXT NOT NULL DEFAULT '',
    has_password INTEGER NOT NULL DEFAULT 0,
    fingers INTEGER NOT NULL DEFAULT 0,
    seen_at TEXT NOT NULL,
    PRIMARY KEY (device_id, badge)
);
CREATE TABLE templates (                    -- fingerprint backup, latest copy per finger
    badge TEXT NOT NULL,
    fid INTEGER NOT NULL,
    valid INTEGER NOT NULL DEFAULT 1,
    template BLOB NOT NULL,
    device_id INTEGER,
    captured_at TEXT NOT NULL,
    PRIMARY KEY (badge, fid)
);
CREATE TABLE user_backup (                  -- user record as stored on a device, for restore
    badge TEXT PRIMARY KEY,
    name TEXT, privilege INTEGER, password TEXT, group_id TEXT, card TEXT,
    device_id INTEGER, captured_at TEXT NOT NULL
);
CREATE TABLE jobs (
    id INTEGER PRIMARY KEY,
    kind TEXT NOT NULL,
    params TEXT NOT NULL,
    title TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'queued',  -- queued | running | done | failed | cancelled
    progress INTEGER NOT NULL DEFAULT 0,
    log TEXT NOT NULL DEFAULT '',
    created_by TEXT,
    created_at TEXT NOT NULL,
    started_at TEXT,
    finished_at TEXT
);
CREATE INDEX jobs_status ON jobs(status, id);
ALTER TABLE devices ADD COLUMN fingers_on_device INTEGER;
ALTER TABLE devices ADD COLUMN faces_on_device INTEGER;
ALTER TABLE devices ADD COLUMN users_cap INTEGER;
ALTER TABLE devices ADD COLUMN fingers_cap INTEGER;
ALTER TABLE devices ADD COLUMN faces_cap INTEGER;
ALTER TABLE devices ADD COLUMN last_scan_at TEXT;
"""

V5 = """
ALTER TABLE punches ADD COLUMN location TEXT;          -- machine number as the old program showed it ("Location ID")
ALTER TABLE devices ADD COLUMN machine_number INTEGER;
-- first versions stored the verify type and the punch state the wrong way round for device pulls
UPDATE punches SET state=verify, verify=state WHERE source='device';
"""

V6 = """
ALTER TABLE devices ADD COLUMN info TEXT;              -- JSON: options and counters read by "Read device"
ALTER TABLE devices ADD COLUMN info_at TEXT;
ALTER TABLE device_users ADD COLUMN has_face INTEGER NOT NULL DEFAULT 0;
CREATE TABLE faces (                        -- face backup, latest copy per person
    badge TEXT PRIMARY KEY,
    face_index INTEGER NOT NULL DEFAULT 50,
    template BLOB NOT NULL,
    face_version TEXT,                      -- ZKFaceVersion of the device it came from; only same version can receive it
    device_id INTEGER,
    captured_at TEXT
);
"""

DEFAULT_SETTINGS = {
    # Times the Activity Board owns the devices: no pulls and no port checks.
    "quiet_windows": [["07:00", "08:15"], ["15:00", "16:30"], ["18:00", "21:00"], ["01:30", "03:00"]],
    "work_start": "07:00",
    "work_end": "15:00",
    "grace_minutes": 15,
    "weekend": [4],                       # Monday=0 ... Friday=4
    "enroll_device_id": None,             # where new employees are enrolled; default source for copies
    "maintenance_time": "22:00",          # nightly: scan users + fingerprint backup, then clock sync
    "clock_sync": True,
}

_write_lock = threading.Lock()


def now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def connect():
    con = sqlite3.connect(config.DB_PATH, timeout=30)
    con.row_factory = sqlite3.Row
    con.create_function("norm_no", 1, norm_no, deterministic=True)
    con.execute("PRAGMA foreign_keys=ON")
    return con


def _migrate_v1_to_v2(con):
    """v1 was the first quick service. Keep the sign-in accounts; punches since v1 are still on the
    devices and come back with the next pull, and the legacy import brings the history."""
    accounts = []
    if con.execute("SELECT 1 FROM sqlite_master WHERE name='accounts'").fetchone():
        cols = {r[1] for r in con.execute("PRAGMA table_info(accounts)")}
        if "is_admin" in cols:
            accounts = con.execute("SELECT username, pw_hash, is_admin FROM accounts").fetchall()
    for t in ("punches", "events", "employees", "devices", "accounts"):
        con.execute(f"DROP TABLE IF EXISTS {t}")
    con.executescript(V2)
    for a in accounts:
        con.execute("INSERT INTO accounts(username, pw_hash, role, created_at) VALUES (?,?,?,?)",
                    (a[0], a[1], "admin" if a[2] else "hr", now()))


def init():
    con = connect()
    con.execute("PRAGMA journal_mode=WAL")
    version = con.execute("PRAGMA user_version").fetchone()[0]
    if version < 2:
        con.execute("PRAGMA foreign_keys=OFF")
        _migrate_v1_to_v2(con)
        con.execute("PRAGMA user_version=2")
        con.execute("PRAGMA foreign_keys=ON")
        version = 2
    if version < 3:
        con.executescript(V3)
        con.execute("PRAGMA user_version=3")
    if version < 4:
        con.executescript(V4)
        con.execute("PRAGMA user_version=4")
    if version < 5:
        con.executescript(V5)
        con.execute("PRAGMA user_version=5")
    if version < 6:
        con.executescript(V6)
        con.execute("PRAGMA user_version=6")
    for k, v in DEFAULT_SETTINGS.items():
        con.execute("INSERT OR IGNORE INTO settings(key, value) VALUES (?,?)", (k, json.dumps(v)))
    con.commit()
    con.close()


def norm_no(value):
    """Employee numbers are compared without leading zeros (0067 and 67 are the same person)."""
    v = str(value or "").strip()
    return v.lstrip("0") or ("0" if v else "")


@contextmanager
def write():
    with _write_lock:
        con = connect()
        try:
            yield con
            con.commit()
        except Exception:
            con.rollback()
            raise
        finally:
            con.close()


def read():
    return connect()


def get_settings(con=None):
    own = con is None
    con = con or connect()
    try:
        return {r["key"]: json.loads(r["value"]) for r in con.execute("SELECT key, value FROM settings")}
    finally:
        if own:
            con.close()


def audit(con, user, action, target=None, detail=None):
    con.execute("INSERT INTO audit(ts, username, action, target, detail) VALUES (?,?,?,?,?)",
                (now(), user, action, target, json.dumps(detail, ensure_ascii=False) if isinstance(detail, (dict, list)) else detail))
