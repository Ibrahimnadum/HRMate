"""Device jobs: scan users, copy employees between devices, push names, remove users, clock sync, restart.

Jobs run one at a time in the collector thread, so a device never has two sessions open, and never
inside an Activity Board window: a job that meets a window stops and goes back to the queue (every job
is safe to run again from the start).
"""
import json
import logging
from contextlib import contextmanager
from datetime import datetime

from . import db

log = logging.getLogger("jobs")
NAME_MAX = 24
USER_ADMIN = 14


class Paused(Exception):
    pass


def enqueue(kind, params, title, user):
    with db.write() as con:
        jid = con.execute("INSERT INTO jobs(kind, params, title, created_by, created_at) VALUES (?,?,?,?,?)",
                          (kind, json.dumps(params), title, user, db.now())).lastrowid
        db.audit(con, user, "job_queued", title, params)
    return jid


class Job:
    def __init__(self, row):
        self.id = row["id"]
        self.kind = row["kind"]
        self.params = json.loads(row["params"])
        self.title = row["title"]
        self.user = row["created_by"] or "system"

    def say(self, text, progress=None):
        line = f"{datetime.now():%H:%M:%S}  {text}\n"
        with db.write() as con:
            con.execute("UPDATE jobs SET log=log||?, progress=COALESCE(?, progress) WHERE id=?", (line, progress, self.id))
        log.info("job %s: %s", self.id, text)


# ---------- device session ----------

@contextmanager
def session(dev, write=False):
    from .collector import zk_client, _pulling
    _pulling.add(dev["id"])
    conn = zk_client(dev).connect()
    try:
        if write:
            conn.disable_device()          # the device shows "working" and ignores punches for a moment
        yield conn
    finally:
        try:
            if write:
                conn.enable_device()
        except Exception:
            pass
        try:
            conn.disconnect()
        except Exception:
            pass
        _pulling.discard(dev["id"])


def _devices(ids=None):
    with db.read() as con:
        devs = con.execute("SELECT * FROM devices WHERE retired=0 AND ip IS NOT NULL AND ip<>'' ORDER BY name").fetchall()
    if ids:
        devs = [d for d in devs if d["id"] in ids]
    else:
        devs = [d for d in devs if d["active"]]
    return devs


def _guard():
    from .collector import quiet_until
    q = quiet_until(margin=1)
    if q:
        raise Paused(q)


def _name24(name):
    return " ".join((name or "").split())[:NAME_MAX]


def _store_scan(dev, users, fingers, conn=None):
    """Replace the device's user list and refresh the fingerprint backup."""
    by_uid = {u.uid: u for u in users}
    counts = {}
    for f in fingers:
        counts[f.uid] = counts.get(f.uid, 0) + 1
    t = db.now()
    with db.write() as con:
        con.execute("DELETE FROM device_users WHERE device_id=?", (dev["id"],))
        for u in users:
            badge = str(u.user_id).strip()
            con.execute("INSERT OR REPLACE INTO device_users(device_id, badge, uid, name, privilege, card, has_password, fingers, seen_at) "
                        "VALUES (?,?,?,?,?,?,?,?,?)",
                        (dev["id"], badge, u.uid, (u.name or "").strip(), u.privilege, str(u.card or ""),
                         1 if u.password else 0, counts.get(u.uid, 0), t))
            con.execute("INSERT INTO user_backup(badge, name, privilege, password, group_id, card, device_id, captured_at) "
                        "VALUES (?,?,?,?,?,?,?,?) ON CONFLICT(badge) DO UPDATE SET name=excluded.name, privilege=excluded.privilege, "
                        "password=excluded.password, group_id=excluded.group_id, card=excluded.card, device_id=excluded.device_id, "
                        "captured_at=excluded.captured_at",
                        (badge, (u.name or "").strip(), u.privilege, u.password or "", str(u.group_id or ""), str(u.card or ""), dev["id"], t))
        for f in fingers:
            u = by_uid.get(f.uid)
            if not u or not f.template:
                continue
            con.execute("INSERT INTO templates(badge, fid, valid, template, device_id, captured_at) VALUES (?,?,?,?,?,?) "
                        "ON CONFLICT(badge, fid) DO UPDATE SET valid=excluded.valid, template=excluded.template, "
                        "device_id=excluded.device_id, captured_at=excluded.captured_at",
                        (str(u.user_id).strip(), f.fid, f.valid, f.template, dev["id"], t))
        sizes = {}
        if conn is not None:
            for k in ("fingers", "faces", "users_cap", "fingers_cap", "faces_cap"):
                sizes[k] = getattr(conn, k, None)
        con.execute("UPDATE devices SET users_on_device=?, fingers_on_device=?, faces_on_device=COALESCE(?, faces_on_device), "
                    "users_cap=COALESCE(?, users_cap), fingers_cap=COALESCE(?, fingers_cap), faces_cap=COALESCE(?, faces_cap), "
                    "last_scan_at=? WHERE id=?",
                    (len(users), len(fingers), sizes.get("faces"), sizes.get("users_cap"), sizes.get("fingers_cap"),
                     sizes.get("faces_cap"), t, dev["id"]))


def _face_version(conn):
    """ZKFaceVersion of a device, or None when it has no face function."""
    try:
        v = conn.option("ZKFaceVersion")
        on = conn.option("FaceFunOn")
    except Exception:
        return None
    if not v or on == "0":
        return None
    return v


def _read_faces(job, dev, conn, users, badges=None):
    """Back up the face template of every user (or the given badges) on a device. Returns {badge: bytes}."""
    version = _face_version(conn)
    if not version:
        return {}
    found = {}
    for u in users:
        b = str(u.user_id).strip()
        if badges is not None and b not in badges:
            continue
        try:
            tpl = conn.get_face(b)
        except Exception as exc:
            log.warning("face read #%s on %s: %s", b, dev["name"], exc)
            tpl = None
        if tpl:
            found[b] = tpl
    t = db.now()
    with db.write() as con:
        for b, tpl in found.items():
            con.execute("INSERT INTO faces(badge, face_index, template, face_version, device_id, captured_at) VALUES (?,50,?,?,?,?) "
                        "ON CONFLICT(badge) DO UPDATE SET template=excluded.template, face_version=excluded.face_version, "
                        "device_id=excluded.device_id, captured_at=excluded.captured_at", (b, tpl, version, dev["id"], t))
        if badges is None:
            con.execute("UPDATE device_users SET has_face=0 WHERE device_id=?", (dev["id"],))
        for b in found:
            con.execute("UPDATE device_users SET has_face=1 WHERE device_id=? AND badge=?", (dev["id"], b))
        if badges is None:
            con.execute("UPDATE devices SET faces_on_device=? WHERE id=?", (len(found), dev["id"]))
    if job:
        job.say(f"{dev['name']}: {len(found)} face(s) backed up")
    return found


# ---------- job kinds ----------

def scan(job):
    devs = _devices(job.params.get("device_ids"))
    failed = []
    for i, d in enumerate(devs):
        _guard()
        job.say(f"Reading users and fingerprints from {d['name']} ...", int(i / len(devs) * 100))
        try:
            with session(d) as conn:
                users = conn.get_users() or []
                fingers = conn.get_templates() or []
                conn.read_sizes()
                _store_scan(d, users, fingers, conn)
                job.say(f"{d['name']}: {len(users)} users, {len(fingers)} fingerprints backed up. Reading faces ...")
                _read_faces(job, d, conn, users)
        except Paused:
            raise
        except Exception as exc:              # one bad device must not stop the others
            failed.append(d["name"])
            job.say(f"{d['name']}: could not be read ({type(exc).__name__}: {exc}). Skipped.")
    if failed:
        job.say(f"Finished, but {len(failed)} device(s) were skipped: {', '.join(failed)}")


def _source_data(job, badges, source):
    """{badge: (user_fields, [Finger])} from a device or from the backup in the database."""
    from zk.finger import Finger
    out = {}
    if source == "backup":
        with db.read() as con:
            for b in badges:
                u = con.execute("SELECT * FROM user_backup WHERE badge=?", (b,)).fetchone()
                fs = con.execute("SELECT * FROM templates WHERE badge=? ORDER BY fid", (b,)).fetchall()
                if not u and not fs:
                    job.say(f"#{b}: nothing in the backup, skipped")
                    continue
                fields = {"privilege": u["privilege"] if u else 0, "password": (u["password"] if u else "") or "",
                          "group_id": (u["group_id"] if u else "") or "", "card": int(u["card"] or 0) if u and str(u["card"] or "").isdigit() else 0,
                          "name": u["name"] if u else ""}
                face = con.execute("SELECT template, face_version FROM faces WHERE badge=?", (b,)).fetchone()
                out[b] = (fields, [Finger(0, f["fid"], f["valid"], f["template"]) for f in fs],
                          (bytes(face["template"]), face["face_version"]) if face else None)
        return out
    with db.read() as con:
        dev = con.execute("SELECT * FROM devices WHERE id=?", (int(source),)).fetchone()
    if not dev:
        raise RuntimeError("Source device not found")
    _guard()
    job.say(f"Reading from source {dev['name']} ...")
    with session(dev) as conn:
        users = {str(u.user_id).strip(): u for u in conn.get_users() or []}
        fingers = conn.get_templates() or []
        conn.read_sizes()
        _store_scan(dev, list(users.values()), fingers, conn)
        version = _face_version(conn)
        faces = _read_faces(job, dev, conn, list(users.values()), set(badges)) if version else {}
    by_uid = {}
    for f in fingers:
        by_uid.setdefault(f.uid, []).append(f)
    for b in badges:
        u = users.get(b)
        if not u:
            job.say(f"#{b}: not on {dev['name']}, skipped")
            continue
        out[b] = ({"privilege": u.privilege, "password": u.password or "", "group_id": str(u.group_id or ""),
                   "card": int(u.card or 0), "name": u.name or ""}, by_uid.get(u.uid, []),
                  (faces[b], version) if b in faces else None)
    return out


def copy(job):
    """Copy employees (user record + fingerprints + card + password) to target devices. Names come from the database."""
    from zk.user import User
    badges = [str(b) for b in job.params["badges"]]
    source = job.params.get("source")
    targets = [d for d in _devices(job.params.get("targets")) if str(d["id"]) != str(source)]
    data = _source_data(job, badges, source)
    if not data:
        job.say("Nothing to copy.")
        return
    with db.read() as con:
        names = {r["badge"]: r["name"] for r in con.execute(
            f"SELECT badge, name FROM employees WHERE badge IN ({','.join('?' * len(data))})", list(data))}
    for i, d in enumerate(targets):
        _guard()
        job.say(f"Writing {len(data)} employee(s) to {d['name']} ...", int(i / max(1, len(targets)) * 100))
        with session(d, write=True) as conn:
            existing = {str(u.user_id).strip(): u for u in conn.get_users() or []}
            next_uid = max([u.uid for u in existing.values()] + [0]) + 1
            target_face = _face_version(conn)
            for b, (f, fingers, face) in data.items():
                cur = existing.get(b)
                uid = cur.uid if cur else next_uid
                if not cur:
                    next_uid += 1
                name = _name24(names.get(b) or f["name"])
                user = User(uid, name, f["privilege"], f["password"], f["group_id"], b, f["card"])
                if fingers:
                    conn.save_user_template(user, [_finger_for(uid, x) for x in fingers])
                else:
                    conn.set_user(uid=uid, name=name, privilege=f["privilege"], password=f["password"],
                                  group_id=f["group_id"], user_id=b, card=f["card"])
                face_note = ""
                if face:
                    if not target_face:
                        face_note = ", face skipped (no face function)"
                    elif face[1] and face[1] != target_face:
                        face_note = f", face skipped (face version {face[1]} vs {target_face})"
                    else:
                        try:
                            conn.set_face(b, face[0])
                            face_note = ", face"
                        except Exception as exc:
                            face_note = f", face FAILED ({exc})"
                job.say(f"  {d['name']}: #{b} {name} - {'updated' if cur else 'added'}, {len(fingers)} fingerprint(s){face_note}")
            try:
                conn.refresh_data()
            except Exception:
                pass
            users = conn.get_users() or []
            fingers_all = conn.get_templates() or []
            conn.read_sizes()
            _store_scan(d, users, fingers_all, conn)
            if target_face:
                _read_faces(None, d, conn, users)


def _finger_for(uid, f):
    from zk.finger import Finger
    return Finger(uid, f.fid, f.valid, f.template)


def push_names(job):
    """Write the database names (max 24 characters) to the devices for the chosen employees (or everyone)."""
    badges = set(str(b) for b in job.params.get("badges") or [])
    with db.read() as con:
        names = {r["badge"]: _name24(r["name"]) for r in con.execute("SELECT badge, name FROM employees WHERE name<>''")}
    devs = _devices(job.params.get("device_ids"))
    for i, d in enumerate(devs):
        _guard()
        job.say(f"Checking names on {d['name']} ...", int(i / len(devs) * 100))
        changed = 0
        with session(d, write=True) as conn:
            for u in conn.get_users() or []:
                b = str(u.user_id).strip()
                if (badges and b not in badges) or b not in names or names[b] == (u.name or "").strip():
                    continue
                conn.set_user(uid=u.uid, name=names[b], privilege=u.privilege, password=u.password or "",
                              group_id=str(u.group_id or ""), user_id=u.user_id, card=u.card or 0)
                changed += 1
            users = conn.get_users() or []
            fingers = conn.get_templates() or []
            conn.read_sizes()
            _store_scan(d, users, fingers, conn)
        job.say(f"{d['name']}: {changed} name(s) updated")


def remove(job):
    """Remove employees from devices. Their user record and fingerprints are backed up first."""
    badges = set(str(b) for b in job.params["badges"])
    devs = _devices(job.params.get("device_ids"))
    for i, d in enumerate(devs):
        _guard()
        job.say(f"Backing up and removing on {d['name']} ...", int(i / len(devs) * 100))
        removed = 0
        with session(d, write=True) as conn:
            users = conn.get_users() or []
            fingers = conn.get_templates() or []
            _store_scan(d, users, fingers)          # backup before deleting
            for u in users:
                if str(u.user_id).strip() in badges:
                    conn.delete_user(uid=u.uid)
                    removed += 1
            users = conn.get_users() or []
            fingers = conn.get_templates() or []
            conn.read_sizes()
            _store_scan(d, users, fingers, conn)
        job.say(f"{d['name']}: {removed} removed")
    if job.params.get("deactivate"):
        with db.write() as con:
            q = ",".join("?" * len(badges))
            con.execute(f"UPDATE employees SET active=0, updated_at=? WHERE badge IN ({q})", [db.now(), *badges])
            db.audit(con, job.user, "employees_deactivated", f"{len(badges)} employees", sorted(badges))
        job.say(f"{len(badges)} employee(s) marked inactive")


def clock(job):
    devs = _devices(job.params.get("device_ids"))
    for i, d in enumerate(devs):
        _guard()
        with session(d) as conn:
            before = conn.get_time()
            conn.set_time(datetime.now())
        drift = int((before - datetime.now()).total_seconds()) if isinstance(before, datetime) else None
        with db.write() as con:
            con.execute("UPDATE devices SET device_time_offset=0 WHERE id=?", (d["id"],))
        job.say(f"{d['name']}: clock set" + (f" (was {abs(drift)} s {'ahead' if drift > 0 else 'behind'})" if drift is not None else ""),
                int((i + 1) / len(devs) * 100))


def restart(job):
    devs = _devices(job.params.get("device_ids"))
    for d in devs:
        _guard()
        with session(d) as conn:
            conn.restart()
        with db.write() as con:
            con.execute("INSERT INTO events(device_id, ts, kind, detail) VALUES (?,?, 'restart', ?)",
                        (d["id"], db.now(), f"Restarted by {job.user}"))
        job.say(f"{d['name']}: restart sent")


KINDS = {"scan": scan, "copy": copy, "push_names": push_names, "remove": remove, "clock": clock, "restart": restart}


# ---------- device control (the old "Device manage" window) ----------

def _dev(did):
    with db.read() as con:
        d = con.execute("SELECT * FROM devices WHERE id=?", (int(did),)).fetchone()
    if not d:
        raise RuntimeError("Device not found")
    return d


def _read_info(conn, dev):
    """Read every known option and counter and store them on the device row."""
    from . import devopts
    opts = {}
    for k in devopts.OPTIONS:
        try:
            v = conn.option(k)
        except Exception:
            v = None
        if v is not None:
            opts[k] = v
    raw = []
    try:
        raw = conn.sizes_raw()
    except Exception:
        pass
    sizes = {name: raw[i] for i, name in devopts.SIZE_FIELDS.items() if i < len(raw)}
    firmware = time = None
    try:
        firmware = conn.get_firmware_version()
    except Exception:
        pass
    try:
        time = conn.get_time()
    except Exception:
        pass
    users = conn.get_users() or []
    admins = sum(1 for u in users if u.privilege == USER_ADMIN)
    passwords = sum(1 for u in users if u.password)
    info = {"options": opts, "sizes": sizes, "raw_sizes": raw, "firmware": firmware, "admins": admins,
            "passwords": passwords, "device_time": time.strftime("%Y-%m-%d %H:%M:%S") if isinstance(time, datetime) else None}
    t = db.now()
    serial = opts.get("~SerialNumber") or None
    with db.write() as con:
        if serial:
            from .collector import _move_serial
            _move_serial(con, serial, dev)
        con.execute(
            "UPDATE devices SET info=?, info_at=?, serial=COALESCE(?, serial), firmware=COALESCE(?, firmware), "
            "model=CASE WHEN ?<>'' THEN ? ELSE model END, users_on_device=COALESCE(?, users_on_device), "
            "fingers_on_device=COALESCE(?, fingers_on_device), records_on_device=COALESCE(?, records_on_device), "
            "faces_on_device=COALESCE(?, faces_on_device), users_cap=COALESCE(?, users_cap), "
            "fingers_cap=COALESCE(?, fingers_cap), faces_cap=COALESCE(?, faces_cap), "
            "machine_number=COALESCE(?, machine_number) WHERE id=?",
            (json.dumps(info), t, serial, firmware, opts.get("~DeviceName", ""), opts.get("~DeviceName", ""),
             sizes.get("users"), sizes.get("fingers"), sizes.get("records"), sizes.get("faces"),
             sizes.get("users_cap"), sizes.get("fingers_cap"), sizes.get("faces_cap"),
             int(opts["DeviceID"]) if str(opts.get("DeviceID", "")).isdigit() else None, dev["id"]))
    return info


def info(job):
    d = _dev(job.params["device_id"])
    _guard()
    job.say(f"Reading settings and counters from {d['name']} ...")
    with session(d) as conn:
        inf = _read_info(conn, d)
    s = inf["sizes"]
    job.say(f"{d['name']}: {len(inf['options'])} settings read; {s.get('users', '?')} users, "
            f"{s.get('fingers', '?')} fingerprints, {s.get('faces', '?')} faces, {s.get('records', '?')} records")


def options(job):
    """Write device options (Date format, Voice, Power ...), then read them back."""
    from . import devopts
    d = _dev(job.params["device_id"])
    values = {k: devopts.check_value(k, v) for k, v in job.params["values"].items()}
    _guard()
    with session(d, write=True) as conn:
        for k, v in values.items():
            conn.set_option(k, v)
            job.say(f"{d['name']}: {devopts.OPTIONS[k][1]} set to {v}")
        conn.refresh_options()
        bad = [k for k, v in values.items() if (conn.option(k) or "") != v]
        inf = _read_info(conn, d)
    if bad:
        raise RuntimeError("The device did not keep: " + ", ".join(devopts.OPTIONS[k][1] for k in bad))


def comm(job):
    """Change network settings, machine number or comm key. The server's record is updated to match,
    and the device is checked again on its new address."""
    import time as _time
    from . import devopts
    from .collector import zk_client
    d = _dev(job.params["device_id"])
    values = {k: devopts.check_value(k, v) for k, v in job.params["values"].items() if k in devopts.COMM_KEYS}
    if not values:
        job.say("Nothing to change.")
        return
    _guard()
    with session(d, write=True) as conn:
        for k, v in values.items():
            conn.set_option(k, v)
            job.say(f"{d['name']}: {devopts.OPTIONS[k][1]} -> {'****' if k == 'COMKey' else v}")
        conn.refresh_options()
        if "IPAddress" in values or "NetMask" in values or "GATEIPAddress" in values:
            job.say("Restarting the device so the network change takes effect ...")
            try:
                conn.restart()
            except Exception:
                pass
    upd = {}
    if "IPAddress" in values:
        upd["ip"] = values["IPAddress"]
    if "COMKey" in values:
        upd["commkey"] = int(values["COMKey"])
    if "DeviceID" in values:
        upd["machine_number"] = int(values["DeviceID"])
    if upd:
        with db.write() as con:
            con.execute(f"UPDATE devices SET {', '.join(f'{k}=?' for k in upd)} WHERE id=?", [*upd.values(), d["id"]])
            db.audit(con, job.user, "device_comm_changed", d["name"],
                     {k: ("***" if k == "commkey" else v) for k, v in upd.items()})
    d = _dev(d["id"])
    for attempt in range(9):                    # up to ~90 s for a restart
        try:
            with session(d) as conn:
                _read_info(conn, d)
            job.say(f"{d['name']} answers on {d['ip']} with the new settings.")
            return
        except Exception:
            _time.sleep(10)
    raise RuntimeError(f"{d['name']} does not answer on {d['ip']} yet. Check it at the device; the server already uses the new settings.")


def _save_records(dev, records):
    """Store device records like a pull does. Returns how many are still missing from the database afterwards."""
    t = db.now()
    location = str(dev["machine_number"]) if dev["machine_number"] is not None else None
    rows = [(str(r.user_id).strip(), r.timestamp.strftime("%Y-%m-%d %H:%M:%S"), getattr(r, "punch", None), r.status)
            for r in records]
    with db.write() as con:
        for b, ts, st, vf in rows:
            con.execute("INSERT OR IGNORE INTO punches(badge, ts, device_id, source, state, verify, location, created_at) "
                        "VALUES (?,?,?,?,?,?,?,?)", (b, ts, dev["id"], "device", st, vf, location, t))
        missing = sum(1 for b, ts, _, _ in rows if not con.execute(
            "SELECT 1 FROM punches WHERE device_id=? AND badge=? AND ts=?", (dev["id"], b, ts)).fetchone())
    return missing


def _secure_records(job, conn, d):
    """Read all records with the device locked, save them, and stop if any is not in the database."""
    job.say(f"Saving every record from {d['name']} before clearing ...")
    records = conn.get_attendance() or []
    missing = _save_records(d, records)
    if missing:
        raise RuntimeError(f"{missing} record(s) could not be saved, nothing was cleared")
    job.say(f"{len(records)} record(s) are safe in the database")
    return len(records)


ACTIONS = {"restart": "Restart", "poweroff": "Power off", "clear_attlog": "Clear attendance records",
           "clear_oplog": "Clear super log", "clear_admin": "Clear admin privilege", "initialize": "Initialize device",
           "voice": "Play a sound"}


def action(job):
    a = job.params["action"]
    d = _dev(job.params["device_id"])
    _guard()
    note = ""
    if a == "restart":
        with session(d) as conn:
            conn.restart()
        note = "restart sent"
    elif a == "poweroff":
        with session(d) as conn:
            conn.poweroff()
        note = "power off sent. It must be switched on at the device"
    elif a == "voice":
        with session(d) as conn:
            conn.test_voice(0)
        note = "played \"Thank you\""
    elif a == "clear_oplog":
        with session(d, write=True) as conn:
            conn.clear_oplog()
            _read_info(conn, d)
        note = "super log cleared"
    elif a == "clear_admin":
        with session(d, write=True) as conn:
            users = conn.get_users() or []
            _store_scan(d, users, conn.get_templates() or [])      # remember who was admin
            conn.clear_admin()
            _read_info(conn, d)
        note = "admin rights removed. The device menu is now open to everyone until an admin is set again"
    elif a == "clear_attlog":
        with session(d, write=True) as conn:
            n = _secure_records(job, conn, d)
            conn.clear_attendance()
            _read_info(conn, d)
        note = f"{n} record(s) cleared from the device"
    elif a == "initialize":
        with session(d, write=True) as conn:
            job.say("Backing up users and fingerprints ...")
            users = conn.get_users() or []
            fingers = conn.get_templates() or []
            _store_scan(d, users, fingers)
            job.say(f"{len(users)} users and {len(fingers)} fingerprints backed up")
            _read_faces(job, d, conn, users)
            _secure_records(job, conn, d)
            conn.clear_data()
            _read_info(conn, d)
        with db.write() as con:
            con.execute("DELETE FROM device_users WHERE device_id=?", (d["id"],))
        note = "device wiped. Copy employees back to it from the backup on the Users on devices page"
    else:
        raise RuntimeError("Unknown action")
    with db.write() as con:
        con.execute("INSERT INTO events(device_id, ts, kind, detail) VALUES (?,?,?,?)",
                    (d["id"], db.now(), "device_" + a, f"{ACTIONS[a]} by {job.user}"))
    job.say(f"{d['name']}: {note}")


def enroll(job):
    """Enroll one finger remotely on the enrollment device, keep it in the backup, and copy it on if asked."""
    from zk.user import User
    from .zkx import EnrollFailed
    badge = str(job.params["badge"])
    fid = int(job.params["fid"])
    d = _dev(job.params["device_id"])
    with db.read() as con:
        emp = con.execute("SELECT name FROM employees WHERE badge=?", (badge,)).fetchone()
    name = _name24(emp["name"] if emp else "")
    _guard()
    with session(d) as conn:
        users = {str(u.user_id).strip(): u for u in conn.get_users() or []}
        u = users.get(badge)
        if not u:
            uid = max([x.uid for x in users.values()] + [0]) + 1
            conn.set_user(uid=uid, name=name, privilege=0, password="", group_id="", user_id=badge, card=0)
            u = User(uid, name, 0, "", "", badge, 0)
            job.say(f"#{badge} {name} added to {d['name']}")
        try:
            conn.delete_user_template(uid=u.uid, temp_id=fid)
        except Exception:
            pass
        job.say(f"Go to {d['name']}: #{badge} {name}, finger {fid}. Press the same finger 3 times.")
        try:
            conn.enroll_finger(badge, fid, job.say)
        except EnrollFailed as e:
            raise RuntimeError(str(e))
        tpl = conn.get_user_template(uid=u.uid, temp_id=fid)
        users = conn.get_users() or []
        fingers = conn.get_templates() or []
        conn.read_sizes()
        _store_scan(d, users, fingers, conn)
    if not tpl:
        raise RuntimeError("The device says it saved the finger, but it could not be read back. Run 'Read users' and check.")
    job.say(f"Fingerprint saved on {d['name']} and in the backup")
    with db.write() as con:
        db.audit(con, job.user, "finger_enrolled", f"#{badge}", {"finger": fid, "device": d["name"]})
    targets = [int(t) for t in job.params.get("copy_to") or [] if int(t) != d["id"]]
    if targets:
        jid = enqueue("copy", {"badges": [badge], "source": "backup", "targets": targets},
                      f"Copy #{badge} to devices after enrollment", job.user)
        job.say(f"Copy to {len(targets)} device(s) queued (job {jid})")


KINDS.update({"info": info, "options": options, "comm": comm, "action": action, "enroll": enroll})


def run_next():
    """Run the oldest queued job. Returns True if one ran."""
    with db.write() as con:
        row = con.execute("SELECT * FROM jobs WHERE status='queued' ORDER BY id LIMIT 1").fetchone()
        if not row:
            return False
        con.execute("UPDATE jobs SET status='running', started_at=COALESCE(started_at, ?) WHERE id=?", (db.now(), row["id"]))
    job = Job(row)
    try:
        KINDS[job.kind](job)
    except Paused as p:
        job.say(f"Paused: Activity Board window until {p}. It continues after the window.")
        with db.write() as con:
            con.execute("UPDATE jobs SET status='queued' WHERE id=?", (job.id,))
        return False
    except Exception as exc:
        log.exception("job %s failed", job.id)
        job.say(f"FAILED: {type(exc).__name__}: {exc}")
        with db.write() as con:
            con.execute("UPDATE jobs SET status='failed', finished_at=? WHERE id=?", (db.now(), job.id))
            db.audit(con, job.user, "job_failed", job.title, str(exc)[:300])
        return True
    job.say("Done.", 100)
    with db.write() as con:
        con.execute("UPDATE jobs SET status='done', finished_at=? WHERE id=?", (db.now(), job.id))
    return True
