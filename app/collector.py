"""Background work: port checks, log pulls, nightly backup.

Quiet windows (settings.quiet_windows) belong to the Activity Board: inside them the service does
not open any connection to the devices. Nothing is ever deleted from a device.
"""
import gzip
import logging
import os
import shutil
import socket
import sqlite3
import threading
import time
from datetime import datetime, timedelta

from . import config, db

log = logging.getLogger("collector")
_pulling = set()
_pull_request = {"ids": None, "want": False}
_wake = threading.Event()
state = {"quiet_until": None, "last_cycle": None, "next_pull": None}


# ---------- quiet windows ----------

def _minutes(hhmm):
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)


def quiet_until(at=None, windows=None, margin=0):
    """End time ('HH:MM') of the quiet window covering `at` (+margin minutes), or None."""
    at = at or datetime.now()
    windows = windows if windows is not None else db.get_settings().get("quiet_windows", [])
    t = (at.hour * 60 + at.minute + margin) % 1440
    for start, end in windows:
        s, e = _minutes(start), _minutes(end)
        inside = s <= t < e if s <= e else (t >= s or t < e)   # a window may cross midnight
        if inside:
            return end
    return None


# ---------- port check ----------

def port_open(ip, port, timeout=3.0):
    try:
        with socket.create_connection((ip, port), timeout=timeout):
            return True
    except OSError:
        return False


def _record_check(con, dev, ok):
    t = db.now()
    if ok:
        if dev["online"] == 0:
            con.execute("INSERT INTO events(device_id, ts, kind) VALUES (?,?, 'up')", (dev["id"], t))
        if dev["online"] != 1:
            con.execute("UPDATE devices SET online=1, status_since=? WHERE id=?", (t, dev["id"]))
        con.execute("UPDATE devices SET fail_count=0, last_check_at=? WHERE id=?", (t, dev["id"]))
    else:
        fails = dev["fail_count"] + 1
        con.execute("UPDATE devices SET fail_count=?, last_check_at=? WHERE id=?", (fails, t, dev["id"]))
        if fails >= config.DOWN_AFTER and dev["online"] != 0:
            con.execute("UPDATE devices SET online=0, status_since=? WHERE id=?", (t, dev["id"]))
            con.execute("INSERT INTO events(device_id, ts, kind, detail) VALUES (?,?, 'down', ?)",
                        (dev["id"], t, f"Port {dev['port']} not answering"))


def check_all():
    with db.read() as con:
        devs = con.execute("SELECT * FROM devices WHERE active=1 AND retired=0 AND ip IS NOT NULL AND ip<>''").fetchall()
    results = {}

    def probe(d):
        results[d["id"]] = True if d["id"] in _pulling else port_open(d["ip"], d["port"])

    threads = [threading.Thread(target=probe, args=(d,)) for d in devs]
    for th in threads:
        th.start()
    for th in threads:
        th.join()
    with db.write() as con:
        for d in devs:
            _record_check(con, d, results[d["id"]])


# ---------- pull ----------

def zk_client(dev):
    from .zkx import ZKX
    return ZKX(dev["ip"], port=dev["port"], timeout=config.PULL_TIMEOUT, password=dev["commkey"],
              force_udp=False, ommit_ping=True)


def _move_serial(con, serial, dev):
    """A device row stands for a place. When a physical device moves to another place (another IP), its serial
    moves with it: the old place keeps its history and gets the serial of whatever device is installed there next."""
    other = con.execute("SELECT id, name FROM devices WHERE serial=? AND id<>?", (serial, dev["id"])).fetchone()
    if not other:
        return
    con.execute("UPDATE devices SET serial=NULL WHERE id=?", (other["id"],))
    t = db.now()
    con.execute("INSERT INTO events(device_id, ts, kind, detail) VALUES (?,?, 'device_moved', ?)",
                (dev["id"], t, f"Device {serial} moved here from {other['name']}"))
    con.execute("INSERT INTO events(device_id, ts, kind, detail) VALUES (?,?, 'device_moved', ?)",
                (other["id"], t, f"Device {serial} moved to {dev['name']}"))
    log.warning("serial %s moved from %s to %s", serial, other["name"], dev["name"])


def pull_device(dev, client_factory=zk_client):
    _pulling.add(dev["id"])
    conn = None
    info = {}
    try:
        conn = client_factory(dev).connect()
        for key, fn in (("serial", "get_serialnumber"), ("firmware", "get_firmware_version"),
                        ("time", "get_time")):
            try:
                info[key] = getattr(conn, fn)()
            except Exception:
                pass
        users = conn.get_users() or []
        records = conn.get_attendance() or []
    except Exception as exc:
        msg = f"{type(exc).__name__}: {exc}"[:300]
        with db.write() as con:
            con.execute("UPDATE devices SET last_pull_try=?, last_error=? WHERE id=?", (db.now(), msg, dev["id"]))
            if not dev["last_error"]:
                con.execute("INSERT INTO events(device_id, ts, kind, detail) VALUES (?,?, 'pull_error', ?)",
                            (dev["id"], db.now(), msg))
        log.warning("pull %s (%s) failed: %s", dev["name"], dev["ip"], msg)
        return 0
    finally:
        if conn is not None:
            try:
                conn.disconnect()
            except Exception:
                pass
        _pulling.discard(dev["id"])

    new = 0
    t = db.now()
    location = str(dev["machine_number"]) if dev["machine_number"] is not None else None
    with db.write() as con:
        dev_id = dev["id"]
        serial = (info.get("serial") or "").strip() or None
        if serial:
            _move_serial(con, serial, dev)
        for u in users:
            badge = str(u.user_id).strip()
            if not badge:
                continue
            name = (u.name or "").strip()
            con.execute(
                "INSERT INTO employees(badge, name, device_name, created_at, updated_at) VALUES (?,?,?,?,?) "
                "ON CONFLICT(badge) DO UPDATE SET device_name=excluded.device_name, "
                "name=CASE WHEN employees.name='' THEN excluded.name ELSE employees.name END",
                (badge, name, name, t, t))
        for r in records:
            # pyzk: .punch is the punch state (0 in, 1 out, ...), .status is the verify type (finger, face, ...)
            cur = con.execute(
                "INSERT OR IGNORE INTO punches(badge, ts, device_id, source, state, verify, location, created_at) "
                "VALUES (?,?,?,?,?,?,?,?)",
                (str(r.user_id).strip(), r.timestamp.strftime("%Y-%m-%d %H:%M:%S"), dev_id, "device",
                 getattr(r, "punch", None), r.status, location, t))
            new += cur.rowcount
        offset = None
        if isinstance(info.get("time"), datetime):
            offset = int((info["time"] - datetime.now()).total_seconds())
        con.execute(
            "UPDATE devices SET last_pull_at=?, last_pull_try=?, last_error=NULL, serial=COALESCE(?, serial), "
            "firmware=COALESCE(?, firmware), records_on_device=?, users_on_device=?, device_time_offset=? WHERE id=?",
            (t, t, serial, info.get("firmware"), len(records), len(users), offset, dev_id))
        if dev["last_error"]:
            con.execute("INSERT INTO events(device_id, ts, kind) VALUES (?,?, 'pull_ok_after_error')", (dev_id, t))
    log.info("pull %s: %d on device, %d new", dev["name"], len(records), new)
    return new


def pull_all(client_factory=zk_client, ids=None):
    with db.read() as con:
        sql = "SELECT * FROM devices WHERE active=1 AND retired=0 AND ip IS NOT NULL AND ip<>''"
        devs = con.execute(sql).fetchall()
    total = 0
    for d in devs:
        if ids and d["id"] not in ids:
            continue
        if not ids and d["online"] == 0:      # offline devices are pulled once they are back
            continue
        if quiet_until(margin=1):             # a window started (or starts within a minute): stop
            break
        total += pull_device(d, client_factory)
    return total


def request_pull(ids=None):
    _pull_request["ids"] = ids
    _pull_request["want"] = True
    _wake.set()


def wake():
    """Wake the loop early (e.g. a device job was queued)."""
    _wake.set()


# ---------- backup ----------

def backup_now():
    os.makedirs(config.BACKUP_DIR, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M")
    tmp = os.path.join(config.BACKUP_DIR, f".tmp-{stamp}.sqlite3")
    src = sqlite3.connect(config.DB_PATH)
    dst = sqlite3.connect(tmp)
    with dst:
        src.backup(dst)
    src.close()
    dst.close()
    out = os.path.join(config.BACKUP_DIR, f"attendance-{stamp}.sqlite3.gz")
    with open(tmp, "rb") as f, gzip.open(out, "wb", compresslevel=6) as g:
        shutil.copyfileobj(f, g)
    os.remove(tmp)
    files = sorted(f for f in os.listdir(config.BACKUP_DIR) if f.startswith("attendance-"))
    for old in files[:-config.BACKUP_KEEP]:
        os.remove(os.path.join(config.BACKUP_DIR, old))
    log.info("backup written: %s", out)
    return out


# ---------- loop ----------

def _maintenance_due(nowdt, last_day):
    """True once a day when the clock passes settings.maintenance_time (and the day has not run yet)."""
    if last_day == nowdt.date():
        return False
    at = db.get_settings().get("maintenance_time") or "22:00"
    return nowdt.strftime("%H:%M") >= at


def _loop():
    from . import jobs
    next_pull = 0.0
    next_check = 0.0
    last_backup_day = None
    last_maint_day = None
    while True:
        mono = time.monotonic()
        nowdt = datetime.now()
        try:
            quiet = quiet_until(nowdt)
            state["quiet_until"] = quiet
            state["last_cycle"] = db.now()
            requested = _pull_request["want"]
            _pull_request["want"] = False
            _wake.clear()
            if not quiet:
                if mono >= next_check:
                    check_all()
                    next_check = mono + config.CHECK_SECONDS
                if requested or mono >= next_pull:
                    ids = _pull_request["ids"]
                    _pull_request["ids"] = None
                    pull_all(ids=ids)
                    next_pull = time.monotonic() + config.PULL_MINUTES * 60
                state["next_pull"] = (nowdt + timedelta(seconds=max(0, next_pull - time.monotonic()))
                                      ).strftime("%Y-%m-%d %H:%M:%S")
                for _ in range(3):              # a few queued device jobs per cycle
                    if quiet_until(margin=1) or not jobs.run_next():
                        break
                if _maintenance_due(nowdt, last_maint_day):
                    last_maint_day = nowdt.date()
                    jobs.enqueue("scan", {}, "Nightly: read users and back up fingerprints", "system")
                    if db.get_settings().get("clock_sync", True):
                        jobs.enqueue("clock", {}, "Nightly: set device clocks", "system")
            elif requested:
                log.info("pull request ignored: quiet window until %s", quiet)
            if nowdt.hour == config.BACKUP_HOUR and last_backup_day != nowdt.date():
                backup_now()
                last_backup_day = nowdt.date()
        except Exception:
            log.exception("collector cycle failed")
        _wake.wait(timeout=5)


def start():
    with db.write() as con:   # a job cut off by a restart starts again
        con.execute("UPDATE jobs SET status='queued', log=log||'(service restarted, job queued again)\n' WHERE status='running'")
    threading.Thread(target=_loop, name="collector", daemon=True).start()
