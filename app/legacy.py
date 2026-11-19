"""Import the history from the old Attendance Management database (converted by tools/convert_mdb.py).
Safe to run again: everything is matched, nothing is duplicated."""
import logging
import os
import sqlite3

from . import db

log = logging.getLogger("legacy")
# old CHECKTYPE -> punch state: I check-in, O check-out, 0 break-out, 1 break-in, i overtime-in, o overtime-out
STATE = {"I": 0, "O": 1, "0": 2, "1": 3, "i": 4, "o": 5}


def seed_devices_from_file(path):
    """First start only: devices.txt (name | ip | port | commkey | off) fills an empty device table."""
    if not os.path.exists(path):
        return
    with db.write() as con:
        if con.execute("SELECT COUNT(*) FROM devices").fetchone()[0]:
            return
        for line in open(path, encoding="utf-8-sig"):
            line = line.split("#", 1)[0].strip()
            parts = [p.strip() for p in line.split("|")]
            if len(parts) < 2:
                continue
            con.execute("INSERT INTO devices(name, ip, port, commkey, active) VALUES (?,?,?,?,?)",
                        (parts[0], parts[1], int(parts[2]) if len(parts) > 2 and parts[2] else 4370,
                         int(parts[3]) if len(parts) > 3 and parts[3] else 0,
                         0 if len(parts) > 4 and parts[4].lower() == "off" else 1))
        db.audit(con, "system", "devices_seeded", path)


def run(path, user="system", echo=print):
    src = sqlite3.connect(path)
    src.row_factory = sqlite3.Row
    t = db.now()
    stats = {}
    with db.write() as con:
        # departments (the root "company" node and -1 mean no department)
        dep_map = {}
        for d in src.execute("SELECT * FROM departments"):
            if not d["parent"]:
                continue
            row = con.execute("SELECT id FROM departments WHERE legacy_id=? OR name=?", (d["id"], d["name"])).fetchone()
            if row:
                dep_map[d["id"]] = row["id"]
                con.execute("UPDATE departments SET legacy_id=? WHERE id=?", (d["id"], row["id"]))
            else:
                dep_map[d["id"]] = con.execute("INSERT INTO departments(name, legacy_id) VALUES (?,?)",
                                               (d["name"], d["id"])).lastrowid
        stats["departments"] = len(dep_map)

        # employees
        badge_of = {}
        added = updated = 0
        cols = {r[1] for r in src.execute("PRAGMA table_info(users)")}
        for u in src.execute("SELECT * FROM users"):
            badge = u["badge"].strip()
            emp_no = (u["emp_no"] or "").strip() if "emp_no" in cols else ""
            phone = (u["phone"] or "").strip() if "phone" in cols else ""
            badge_of[u["id"]] = badge
            dep = dep_map.get(u["dept"])
            cur = con.execute("SELECT * FROM employees WHERE badge=?", (badge,)).fetchone()
            if cur:
                name = cur["name"] if cur["name"] and cur["name"] != cur["device_name"] else (u["name"] or cur["name"])
                con.execute("UPDATE employees SET name=?, department_id=COALESCE(department_id, ?), "
                            "title=CASE WHEN title='' THEN ? ELSE title END, gender=CASE WHEN gender='' THEN ? ELSE gender END, "
                            "card=CASE WHEN card='' THEN ? ELSE card END, emp_no=CASE WHEN emp_no='' THEN ? ELSE emp_no END, "
                            "phone=CASE WHEN phone='' THEN ? ELSE phone END, legacy_id=?, updated_at=? WHERE id=?",
                            (name, dep, u["title"] or "", u["gender"] or "", u["card"] or "", emp_no, phone, u["id"], t, cur["id"]))
                updated += 1
            else:
                con.execute("INSERT INTO employees(badge, name, department_id, title, gender, card, emp_no, phone, legacy_id, "
                            "created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                            (badge, u["name"] or "", dep, u["title"] or "", u["gender"] or "", u["card"] or "", emp_no, phone,
                             u["id"], t, t))
                added += 1
        stats["employees_added"], stats["employees_updated"] = added, updated

        # devices: match by serial, then IP; unknown serials become retired devices kept for their history
        dev_of = {}
        for m in src.execute("SELECT * FROM machines"):
            row = con.execute("SELECT * FROM devices WHERE serial=?", (m["serial"],)).fetchone() or \
                con.execute("SELECT * FROM devices WHERE ip=? AND retired=0", (m["ip"],)).fetchone()
            key = int(m["commkey"]) if str(m["commkey"] or "").isdigit() else 0
            if row:
                con.execute("UPDATE devices SET serial=COALESCE(serial, ?), name=?, commkey=CASE WHEN commkey=0 THEN ? ELSE commkey END, "
                            "machine_number=COALESCE(machine_number, ?) WHERE id=?",
                            (m["serial"], m["alias"] or row["name"], key, m["number"], row["id"]))
                dev_of[m["serial"]] = row["id"]
            else:
                dev_of[m["serial"]] = con.execute(
                    "INSERT INTO devices(serial, name, ip, port, commkey, active, machine_number) VALUES (?,?,?,?,?,?,?)",
                    (m["serial"], m["alias"] or m["serial"], m["ip"], m["port"] or 4370, key, m["enabled"], m["number"])).lastrowid
        for (serial,) in src.execute("SELECT DISTINCT serial FROM punches WHERE serial IS NOT NULL"):
            if serial in dev_of:
                continue
            row = con.execute("SELECT id FROM devices WHERE serial=?", (serial,)).fetchone()
            dev_of[serial] = row["id"] if row else con.execute(
                "INSERT INTO devices(serial, name, active, retired) VALUES (?,?,0,1)", (serial, f"Old device {serial[-4:]}")).lastrowid
        stats["devices"] = len(dev_of)

        # punches
        notes = {(c["userid"], c["ts"]): f"{c['reason']} (by {c['by']})" for c in src.execute("SELECT * FROM corrections")}
        new = manual = 0
        batch = []
        for p in src.execute("SELECT * FROM punches ORDER BY ts"):
            badge = badge_of.get(p["userid"])
            if not badge:
                continue
            state = STATE.get(p["type"])
            if p["serial"] is None:
                if con.execute("SELECT 1 FROM punches WHERE badge=? AND ts=? AND device_id IS NULL", (badge, p["ts"])).fetchone():
                    con.execute("UPDATE punches SET state=?, location=COALESCE(location, ?) WHERE badge=? AND ts=? "
                                "AND device_id IS NULL AND created_by='old program'", (state, p["sensor"], badge, p["ts"]))
                    continue
                con.execute("INSERT INTO punches(badge, ts, device_id, source, state, note, created_by, created_at, location) "
                            "VALUES (?,?,NULL,'manual',?,?,?,?,?)",
                            (badge, p["ts"], state, notes.get((p["userid"], p["ts"]), "Added in the old program"),
                             "old program", t, p["sensor"]))
                manual += 1
                continue
            batch.append((badge, p["ts"], dev_of[p["serial"]], state, p["verify"], t, p["sensor"]))
            if len(batch) >= 5000:
                new += _flush(con, batch)
                batch = []
        new += _flush(con, batch)
        stats["punches_added"], stats["manual_added"] = new, manual
        db.audit(con, user, "legacy_imported", os.path.basename(path), stats)
    src.close()
    for k, v in stats.items():
        echo(f"{k}: {v}")
    return stats


def _flush(con, batch):
    if not batch:
        return 0
    before = con.execute("SELECT COUNT(*) FROM punches").fetchone()[0]
    # re-running fixes state and location of rows imported by earlier versions; device rows keep theirs
    con.executemany("INSERT INTO punches(badge, ts, device_id, source, state, verify, created_at, location) "
                    "VALUES (?,?,?,'legacy',?,?,?,?) ON CONFLICT(device_id, badge, ts) DO UPDATE SET "
                    "state=CASE WHEN punches.source='legacy' THEN excluded.state ELSE punches.state END, "
                    "location=COALESCE(punches.location, excluded.location)", batch)
    return con.execute("SELECT COUNT(*) FROM punches").fetchone()[0] - before
