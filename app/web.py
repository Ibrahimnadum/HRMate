"""JSON API under /api, and the React app for every other path."""
import json
import os
import re
import secrets
from datetime import date, datetime, timedelta
from functools import wraps
from io import BytesIO

from flask import Flask, abort, g, jsonify, request, send_file, send_from_directory, session
from werkzeug.security import check_password_hash, generate_password_hash

from . import collector, config, db, devopts, excel, jobs, oldxls

LOCK_AFTER, LOCK_MINUTES = 5, 15
ROLES = ("admin", "hr", "viewer")
TIME_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


def _secret_key():
    path = os.path.join(config.DATA_DIR, "secret_key")
    if not os.path.exists(path):
        with open(path, "w") as f:
            f.write(secrets.token_hex(32))
    with open(path) as f:
        return f.read().strip()


class ApiError(Exception):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def rows(cur):
    return [dict(r) for r in cur]


def create_app():
    app = Flask(__name__, static_folder=None)
    app.secret_key = _secret_key()
    app.config.update(SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Lax",
                      PERMANENT_SESSION_LIFETIME=timedelta(hours=10), JSON_SORT_KEYS=False)

    @app.errorhandler(ApiError)
    def api_error(e):
        return jsonify(error=str(e)), e.status

    @app.before_request
    def guard():
        g.user = None
        if not request.path.startswith("/api/"):
            return
        name = session.get("user")
        if name:
            with db.read() as con:
                g.user = con.execute("SELECT * FROM accounts WHERE username=?", (name,)).fetchone()
        if request.method not in ("GET", "HEAD") and request.path != "/api/login":
            if not g.user or request.headers.get("X-CSRF") != session.get("csrf"):
                return jsonify(error="Session expired. Sign in again."), 401

    def need(*roles):
        def deco(fn):
            @wraps(fn)
            def wrapper(*a, **kw):
                if not g.user:
                    return jsonify(error="Sign in required."), 401
                if roles and g.user["role"] not in roles:
                    return jsonify(error="Your account cannot do this."), 403
                return fn(*a, **kw)
            return wrapper
        return deco

    def me():
        u = g.user
        return {"username": u["username"], "role": u["role"], "display_name": u["display_name"] or u["username"],
                "csrf": session.get("csrf")}

    # ---------- session ----------

    @app.post("/api/login")
    def login():
        body = request.get_json(silent=True) or {}
        name = str(body.get("username", "")).strip().lower()
        pw = str(body.get("password", ""))
        with db.write() as con:
            acc = con.execute("SELECT * FROM accounts WHERE username=?", (name,)).fetchone()
            if acc and acc["locked_until"] and acc["locked_until"] > db.now():
                raise ApiError(f"Too many attempts. Try again after {acc['locked_until'][11:16]}.", 429)
            if acc and check_password_hash(acc["pw_hash"], pw):
                con.execute("UPDATE accounts SET failed=0, locked_until=NULL, last_login=? WHERE username=?",
                            (db.now(), name))
                session.clear()
                session.permanent = True
                session["user"] = name
                session["csrf"] = secrets.token_hex(16)
                g.user = con.execute("SELECT * FROM accounts WHERE username=?", (name,)).fetchone()
                db.audit(con, name, "sign_in")
                return jsonify(me())
            if acc:
                failed = acc["failed"] + 1
                until = (datetime.now() + timedelta(minutes=LOCK_MINUTES)).strftime("%Y-%m-%d %H:%M:%S") \
                    if failed >= LOCK_AFTER else None
                con.execute("UPDATE accounts SET failed=?, locked_until=? WHERE username=?",
                            (0 if until else failed, until, name))
        raise ApiError("Wrong username or password.", 401)

    @app.post("/api/logout")
    def logout():
        session.clear()
        return jsonify(ok=True)

    @app.get("/api/me")
    @need()
    def get_me():
        return jsonify(me())

    @app.post("/api/me/password")
    @need()
    def change_password():
        body = request.get_json() or {}
        if not check_password_hash(g.user["pw_hash"], str(body.get("current", ""))):
            raise ApiError("Current password is wrong.")
        new = str(body.get("new", ""))
        if len(new) < 8:
            raise ApiError("The new password needs at least 8 characters.")
        with db.write() as con:
            con.execute("UPDATE accounts SET pw_hash=? WHERE username=?", (generate_password_hash(new), g.user["username"]))
            db.audit(con, g.user["username"], "password_changed")
        return jsonify(ok=True)

    # ---------- overview ----------

    @app.get("/api/overview")
    @need()
    def overview():
        today = date.today()
        t0 = today.isoformat()
        t1 = (today + timedelta(days=1)).isoformat()
        with db.read() as con:
            devices = rows(con.execute(
                "SELECT d.*, (SELECT COUNT(*) FROM events e WHERE e.device_id=d.id AND e.kind='down' AND e.ts>=?) AS drops_7d, "
                "(SELECT COUNT(*) FROM punches p WHERE p.device_id=d.id AND p.ts>=? AND p.ts<?) AS punches_today "
                "FROM devices d WHERE d.retired=0 ORDER BY d.name",
                ((datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d %H:%M:%S"), t0, t1)))
            for d in devices:
                d.pop("commkey", None)
            k = con.execute("SELECT COUNT(*) AS punches, COUNT(DISTINCT badge) AS people FROM punches "
                            "WHERE ts>=? AND ts<?", (t0, t1)).fetchone()
            active = con.execute("SELECT COUNT(*) FROM employees WHERE active=1").fetchone()[0]
            hourly = {}
            for day_off, label in ((0, "today"), (7, "last_week")):
                d0 = (today - timedelta(days=day_off)).isoformat()
                d1 = (today - timedelta(days=day_off - 1)).isoformat()
                cnt = dict(con.execute("SELECT CAST(substr(ts,12,2) AS INTEGER) h, COUNT(*) FROM punches "
                                       "WHERE ts>=? AND ts<? GROUP BY h", (d0, d1)).fetchall())
                hourly[label] = [cnt.get(h, 0) for h in range(24)]
            start14 = (today - timedelta(days=13)).isoformat()
            daily = dict(con.execute("SELECT substr(ts,1,10) d, COUNT(DISTINCT badge) FROM punches WHERE ts>=? AND ts<? "
                                     "GROUP BY d", (start14, t1)).fetchall())
            trend = [{"date": (today - timedelta(days=13 - i)).isoformat(),
                      "people": daily.get((today - timedelta(days=13 - i)).isoformat(), 0)} for i in range(14)]
            latest = rows(con.execute(
                "SELECT p.id, p.badge, p.ts, p.source, p.state, e.name, e.emp_no, dep.name AS department, d.name AS device "
                "FROM punches p LEFT JOIN employees e ON e.badge=p.badge LEFT JOIN departments dep ON dep.id=e.department_id "
                "LEFT JOIN devices d ON d.id=p.device_id ORDER BY p.ts DESC LIMIT 12"))
            events = rows(con.execute(
                "SELECT e.*, d.name AS device FROM events e LEFT JOIN devices d ON d.id=e.device_id "
                "ORDER BY e.id DESC LIMIT 15"))
            by_dept = rows(con.execute(
                "SELECT COALESCE(dep.name,'No department') AS department, COUNT(DISTINCT p.badge) AS present, "
                "(SELECT COUNT(*) FROM employees e2 WHERE e2.active=1 AND COALESCE(e2.department_id,-1)=COALESCE(dep.id,-1)) AS total "
                "FROM punches p LEFT JOIN employees e ON e.badge=p.badge LEFT JOIN departments dep ON dep.id=e.department_id "
                "WHERE p.ts>=? AND p.ts<? GROUP BY dep.id ORDER BY present DESC", (t0, t1)))
        return jsonify(devices=devices, today={"punches": k["punches"], "people": k["people"], "active_employees": active},
                       hourly=hourly, trend=trend, latest=latest, events=events, by_department=by_dept,
                       collector=dict(collector.state), now=db.now())

    # ---------- punches ----------

    def punch_query(args):
        try:
            start = date.fromisoformat(args.get("from") or date.today().isoformat())
            end = date.fromisoformat(args.get("to") or date.today().isoformat())
        except ValueError:
            raise ApiError("Dates must be YYYY-MM-DD.")
        if end < start:
            raise ApiError("The start date is after the end date.")
        where = ["p.ts >= ?", "p.ts < ?"]
        params = [start.isoformat(), (end + timedelta(days=1)).isoformat()]
        desc = [f"{start} to {end}"]
        # exact range, like the old program: from a date and time to a date and time (may cross midnight)
        dtf, dtt = args.get("dt_from"), args.get("dt_to")
        if dtf or dtt:
            try:
                a = datetime.strptime((dtf or f"{start}T00:00").replace("T", " ")[:16], "%Y-%m-%d %H:%M")
                b = datetime.strptime((dtt or f"{end}T23:59").replace("T", " ")[:16], "%Y-%m-%d %H:%M")
            except ValueError:
                raise ApiError("Date and time must be YYYY-MM-DD HH:MM.")
            if b < a:
                raise ApiError("The start is after the end.")
            where = ["p.ts >= ?", "p.ts <= ?"]
            params = [a.strftime("%Y-%m-%d %H:%M:00"), b.strftime("%Y-%m-%d %H:%M:59")]
            start, end = a.date(), b.date()
            desc = [f"{a:%Y-%m-%d %H:%M} to {b:%Y-%m-%d %H:%M}"]

        def in_list(col, values, label):
            if values:
                where.append(f"{col} IN ({','.join('?' * len(values))})")
                params.extend(values)
                desc.append(f"{label}: {len(values)} selected")

        in_list("p.badge", args.getlist("badge"), "Employees")
        deps = args.getlist("department")
        if deps:
            parts = []
            ids = [int(d) for d in deps if d.isdigit()]
            if ids:
                parts.append(f"e.department_id IN ({','.join('?' * len(ids))})")
                params.extend(ids)
            if "none" in deps:
                parts.append("e.department_id IS NULL")
            where.append("(" + " OR ".join(parts) + ")")
            desc.append(f"Departments: {len(deps)} selected")
        devs = args.getlist("device")
        if devs:
            parts = []
            ids = [int(d) for d in devs if d.isdigit()]
            if ids:
                parts.append(f"p.device_id IN ({','.join('?' * len(ids))})")
                params.extend(ids)
            if "manual" in devs:
                parts.append("p.device_id IS NULL")
            where.append("(" + " OR ".join(parts) + ")")
            desc.append(f"Devices: {len(devs)} selected")
        in_list("p.source", [s for s in args.getlist("source") if s in ("device", "legacy", "manual")], "Source")
        tf, tt = args.get("time_from"), args.get("time_to")
        if tf and TIME_RE.match(tf):
            where.append("substr(p.ts,12,5) >= ?")
            params.append(tf)
            desc.append(f"From {tf}")
        if tt and TIME_RE.match(tt):
            where.append("substr(p.ts,12,5) <= ?")
            params.append(tt)
            desc.append(f"Until {tt}")
        days = [int(d) for d in args.getlist("weekday") if d.isdigit() and int(d) < 7]
        if days:   # sqlite: 0=Sunday; we use Monday=0
            where.append(f"((CAST(strftime('%w', p.ts) AS INTEGER)+6)%7) IN ({','.join('?' * len(days))})")
            params.extend(days)
            desc.append(f"Weekdays: {len(days)}")
        status = args.get("employee_status")
        if status in ("active", "inactive"):
            where.append("COALESCE(e.active,1)=?")
            params.append(1 if status == "active" else 0)
            desc.append(f"{status.title()} employees")
        q = (args.get("q") or "").strip()
        if q:
            # numbers are the real employee number, never the device ID (they overlap for different people)
            where.append("(norm_no(e.emp_no) = norm_no(?) OR e.name LIKE ? OR p.note LIKE ?)")
            params += [q, f"%{q}%", f"%{q}%"]
            desc.append(f"Search: {q}")
        base = ("FROM punches p LEFT JOIN employees e ON e.badge=p.badge "
                "LEFT JOIN departments dep ON dep.id=e.department_id LEFT JOIN devices d ON d.id=p.device_id "
                "WHERE " + " AND ".join(where))
        return base, params, start, end, "; ".join(desc)

    SORTS = {"ts": "p.ts", "badge": "CAST(p.badge AS INTEGER)", "emp_no": "CAST(norm_no(e.emp_no) AS INTEGER)", "name": "e.name", "department": "dep.name",
             "device": "d.name", "source": "p.source"}
    SELECT = ("SELECT p.id, p.badge, p.ts, p.source, p.state, p.note, p.created_by, p.device_id, p.location, "
              "COALESCE(e.card,'') AS card, "
              "COALESCE(e.name,'') AS name, COALESCE(e.emp_no,'') AS emp_no, e.id AS employee_id, COALESCE(dep.name,'') AS department, d.name AS device ")

    @app.get("/api/punches")
    @need()
    def punches():
        base, params, *_ = punch_query(request.args)
        sort = SORTS.get(request.args.get("sort"), "p.ts")
        direction = "ASC" if request.args.get("dir") == "asc" else "DESC"
        size = min(max(int(request.args.get("size", 50)), 10), 500)
        page = max(int(request.args.get("page", 1)), 1)
        with db.read() as con:
            total = con.execute("SELECT COUNT(*) " + base, params).fetchone()[0]
            people = con.execute("SELECT COUNT(DISTINCT p.badge) " + base, params).fetchone()[0]
            data = rows(con.execute(f"{SELECT}{base} ORDER BY {sort} {direction}, p.ts DESC, p.id DESC LIMIT ? OFFSET ?",
                                    params + [size, (page - 1) * size]))
        return jsonify(rows=data, total=total, people=people, page=page, size=size)

    @app.get("/api/punches/export.xlsx")
    @need()
    def punches_export():
        base, params, start, end, desc = punch_query(request.args)
        if (end - start).days > 400:
            raise ApiError("Pick a period of at most 400 days.")
        with db.read() as con:
            data = rows(con.execute(SELECT + base + " ORDER BY CAST(norm_no(e.emp_no) AS INTEGER), CAST(p.badge AS INTEGER), p.ts", params))
        content = excel.build(data, start, end, desc)
        with db.write() as con:
            db.audit(con, g.user["username"], "export", None, {"filters": desc, "rows": len(data)})
        return send_file(BytesIO(content), as_attachment=True,
                         download_name=f"Attendance_{start}_to_{end}.xlsx",
                         mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

    @app.get("/api/punches/export-old.xls")
    @need()
    def punches_export_old():
        base, params, start, end, desc = punch_query(request.args)
        if (end - start).days > 400:
            raise ApiError("Pick a period of at most 400 days.")
        sql = ("SELECT p.badge, p.ts, p.state, p.location, COALESCE(e.name,'') AS name, COALESCE(e.emp_no,'') AS emp_no, "
               "COALESCE(e.card,'') AS card, COALESCE(dep.name,'Iratec') AS department " + base +
               " ORDER BY COALESCE(dep.legacy_id, CASE WHEN dep.id IS NULL THEN 1 ELSE 1000 + dep.id END), "
               "CAST(p.badge AS INTEGER), p.ts")
        with db.read() as con:
            data = rows(con.execute(sql, params))
        with db.write() as con:
            db.audit(con, g.user["username"], "export_old_format", None, {"filters": desc, "rows": len(data)})
        name = f"Attendance_{start}" + ("" if start == end else f"_to_{end}") + ".xls"
        return send_file(BytesIO(oldxls.build(data, sheet=name[:-4])), as_attachment=True, download_name=name,
                         mimetype="application/vnd.ms-excel")

    @app.post("/api/punches")
    @need("admin", "hr")
    def add_punch():
        body = request.get_json() or {}
        badge = str(body.get("badge", "")).strip()
        try:
            ts = datetime.strptime(str(body.get("ts", "")).replace("T", " ")[:16], "%Y-%m-%d %H:%M")
        except ValueError:
            raise ApiError("Pick a date and time.")
        note = str(body.get("note", "")).strip()
        if not note:
            raise ApiError("Write the reason for the manual punch.")
        with db.write() as con:
            if not con.execute("SELECT 1 FROM employees WHERE badge=?", (badge,)).fetchone():
                raise ApiError("No employee with that ID.")
            ts_s = ts.strftime("%Y-%m-%d %H:%M:%S")
            if con.execute("SELECT 1 FROM punches WHERE badge=? AND ts=?", (badge, ts_s)).fetchone():
                raise ApiError("This employee already has a punch at that exact time.")
            cur = con.execute("INSERT INTO punches(badge, ts, device_id, source, note, created_by, created_at) "
                              "VALUES (?,?,NULL,'manual',?,?,?)", (badge, ts_s, note, g.user["username"], db.now()))
            db.audit(con, g.user["username"], "punch_added", badge, {"ts": ts_s, "note": note})
        return jsonify(id=cur.lastrowid)

    @app.delete("/api/punches/<int:pid>")
    @need("admin", "hr")
    def delete_punch(pid):
        with db.write() as con:
            p = con.execute("SELECT * FROM punches WHERE id=?", (pid,)).fetchone()
            if not p:
                raise ApiError("Not found.", 404)
            if p["source"] != "manual":
                raise ApiError("Only manual punches can be deleted. Device punches are kept as recorded.")
            con.execute("DELETE FROM punches WHERE id=?", (pid,))
            db.audit(con, g.user["username"], "punch_deleted", p["badge"], {"ts": p["ts"], "note": p["note"]})
        return jsonify(ok=True)

    # ---------- employees and departments ----------

    @app.get("/api/employees")
    @need()
    def employees():
        since = (date.today() - timedelta(days=30)).isoformat()
        with db.read() as con:
            data = rows(con.execute(
                "SELECT e.*, dep.name AS department, s.last_punch, COALESCE(r.days30,0) AS days_30 "
                "FROM employees e LEFT JOIN departments dep ON dep.id=e.department_id "
                "LEFT JOIN (SELECT badge, MAX(ts) AS last_punch FROM punches GROUP BY badge) s ON s.badge=e.badge "
                "LEFT JOIN (SELECT badge, COUNT(DISTINCT substr(ts,1,10)) AS days30 FROM punches WHERE ts>=? GROUP BY badge) r "
                "ON r.badge=e.badge ORDER BY CAST(e.badge AS INTEGER), e.badge", (since,)))
        return jsonify(rows=data)

    EMP_FIELDS = ("emp_no", "name", "department_id", "title", "gender", "card", "phone", "active", "note")

    def _emp_values(body):
        vals = {}
        for f in EMP_FIELDS:
            if f in body:
                v = body[f]
                if f == "department_id":
                    v = int(v) if v not in (None, "", "none") else None
                elif f == "active":
                    v = 1 if v else 0
                else:
                    v = str(v or "").strip()
                vals[f] = v
        if len(vals.get("name", "")) > jobs.NAME_MAX:
            raise ApiError(f"Name is limited to {jobs.NAME_MAX} characters, the most the devices can show.")
        if vals.get("emp_no") and not vals["emp_no"].isdigit():
            raise ApiError("Employee No. must be digits only.")
        return vals

    def _check_emp_no(con, emp_no, own_id=None):
        if not emp_no:
            return
        other = con.execute("SELECT id, name, badge FROM employees WHERE emp_no<>'' AND norm_no(emp_no)=norm_no(?) "
                            "AND id IS NOT ?", (emp_no, own_id)).fetchone()
        if other:
            raise ApiError(f"Employee No. {emp_no} already belongs to {other['name'] or 'device ID ' + other['badge']}.")

    @app.get("/api/employees/next")
    @need("admin", "hr")
    def next_numbers():
        """Highest device ID and employee number in use, and the next free ones, for the new-employee form."""
        with db.read() as con:
            used = {r[0] for r in con.execute(
                "SELECT badge FROM employees UNION SELECT badge FROM device_users UNION SELECT badge FROM user_backup")}
            nums = sorted(int(b) for b in used if str(b).isdigit())
            last_badge = nums[-1] if nums else 0
            who = con.execute("SELECT name FROM employees WHERE badge=?", (str(last_badge),)).fetchone()
            emp = con.execute("SELECT emp_no, name FROM employees WHERE emp_no<>'' AND emp_no NOT GLOB '*[^0-9]*' "
                              "ORDER BY CAST(emp_no AS INTEGER) DESC LIMIT 1").fetchone()
        next_emp = ""
        if emp:
            n = int(emp["emp_no"]) + 1
            next_emp = str(n).zfill(len(emp["emp_no"]))     # keep HR's width, e.g. 0412 -> 0413
        return jsonify(badge_last=str(last_badge) if nums else None, badge_last_name=who["name"] if who else None,
                       badge_next=str(last_badge + 1),
                       emp_no_last=emp["emp_no"] if emp else None, emp_no_last_name=emp["name"] if emp else None,
                       emp_no_next=next_emp)

    @app.post("/api/employees")
    @need("admin", "hr")
    def add_employee():
        body = request.get_json() or {}
        badge = str(body.get("badge", "")).strip()
        if not badge.isdigit():
            raise ApiError("Device ID must be a number (the user ID on the devices).")
        vals = _emp_values(body)
        with db.write() as con:
            if con.execute("SELECT 1 FROM employees WHERE badge=?", (badge,)).fetchone():
                raise ApiError("That device ID is already used.")
            _check_emp_no(con, vals.get("emp_no"))
            cols = ["badge", "created_at", "updated_at"] + list(vals)
            con.execute(f"INSERT INTO employees({','.join(cols)}) VALUES ({','.join('?' * len(cols))})",
                        [badge, db.now(), db.now()] + list(vals.values()))
            db.audit(con, g.user["username"], "employee_added", badge, vals)
        return jsonify(ok=True)

    @app.patch("/api/employees/<int:eid>")
    @need("admin", "hr")
    def edit_employee(eid):
        vals = _emp_values(request.get_json() or {})
        if not vals:
            raise ApiError("Nothing to change.")
        with db.write() as con:
            old = con.execute("SELECT * FROM employees WHERE id=?", (eid,)).fetchone()
            if not old:
                raise ApiError("Not found.", 404)
            _check_emp_no(con, vals.get("emp_no"), eid)
            changes = {k: [old[k], v] for k, v in vals.items() if old[k] != v}
            if changes:
                con.execute(f"UPDATE employees SET {', '.join(f'{k}=?' for k in vals)}, updated_at=? WHERE id=?",
                            list(vals.values()) + [db.now(), eid])
                db.audit(con, g.user["username"], "employee_changed", old["badge"], changes)
        return jsonify(ok=True)

    @app.post("/api/employees/bulk")
    @need("admin", "hr")
    def bulk_employees():
        body = request.get_json() or {}
        ids = [int(i) for i in body.get("ids", [])]
        vals = {k: v for k, v in _emp_values(body.get("set", {})).items() if k in ("department_id", "active")}
        if not ids or not vals:
            raise ApiError("Select employees and a change.")
        with db.write() as con:
            q = ",".join("?" * len(ids))
            con.execute(f"UPDATE employees SET {', '.join(f'{k}=?' for k in vals)}, updated_at=? WHERE id IN ({q})",
                        list(vals.values()) + [db.now()] + ids)
            db.audit(con, g.user["username"], "employees_bulk_changed", f"{len(ids)} employees", vals)
        return jsonify(ok=True, changed=len(ids))

    @app.get("/api/departments")
    @need()
    def departments():
        with db.read() as con:
            return jsonify(rows=rows(con.execute(
                "SELECT dep.*, (SELECT COUNT(*) FROM employees e WHERE e.department_id=dep.id AND e.active=1) AS employees "
                "FROM departments dep ORDER BY dep.name")))

    @app.post("/api/departments")
    @need("admin", "hr")
    def add_department():
        name = str((request.get_json() or {}).get("name", "")).strip()
        if not name:
            raise ApiError("Write a name.")
        with db.write() as con:
            if con.execute("SELECT 1 FROM departments WHERE name=?", (name,)).fetchone():
                raise ApiError("That department exists.")
            con.execute("INSERT INTO departments(name) VALUES (?)", (name,))
            db.audit(con, g.user["username"], "department_added", name)
        return jsonify(ok=True)

    @app.patch("/api/departments/<int:did>")
    @need("admin", "hr")
    def rename_department(did):
        name = str((request.get_json() or {}).get("name", "")).strip()
        if not name:
            raise ApiError("Write a name.")
        with db.write() as con:
            old = con.execute("SELECT name FROM departments WHERE id=?", (did,)).fetchone()
            if not old:
                raise ApiError("Not found.", 404)
            con.execute("UPDATE departments SET name=? WHERE id=?", (name, did))
            db.audit(con, g.user["username"], "department_renamed", old["name"], name)
        return jsonify(ok=True)

    @app.delete("/api/departments/<int:did>")
    @need("admin")
    def delete_department(did):
        with db.write() as con:
            old = con.execute("SELECT name FROM departments WHERE id=?", (did,)).fetchone()
            if not old:
                raise ApiError("Not found.", 404)
            con.execute("UPDATE employees SET department_id=NULL WHERE department_id=?", (did,))
            con.execute("DELETE FROM departments WHERE id=?", (did,))
            db.audit(con, g.user["username"], "department_deleted", old["name"])
        return jsonify(ok=True)

    # ---------- devices ----------

    @app.get("/api/devices")
    @need()
    def devices():
        with db.read() as con:
            data = rows(con.execute(
                "SELECT d.*, (SELECT COUNT(*) FROM punches p WHERE p.device_id=d.id) AS punches_stored, "
                "(SELECT MAX(ts) FROM punches p WHERE p.device_id=d.id) AS last_punch FROM devices d "
                "ORDER BY d.retired, d.name"))
        for d in data:
            d["has_commkey"] = bool(d.pop("commkey"))
        return jsonify(rows=data, collector=dict(collector.state))

    DEV_FIELDS = {"name": str, "ip": str, "port": int, "commkey": int, "model": str, "location": str,
                  "active": bool, "retired": bool}

    def _dev_values(body):
        vals = {}
        for f, typ in DEV_FIELDS.items():
            if f in body and body[f] is not None and body[f] != "":
                try:
                    vals[f] = (1 if body[f] else 0) if typ is bool else typ(body[f]) if typ is int else str(body[f]).strip()
                except ValueError:
                    raise ApiError(f"{f} must be a number.")
        if "ip" in vals and not re.match(r"^\d{1,3}(\.\d{1,3}){3}$", vals["ip"]):
            raise ApiError("IP looks wrong.")
        return vals

    @app.post("/api/devices")
    @need("admin")
    def add_device():
        vals = _dev_values(request.get_json() or {})
        if not vals.get("name") or not vals.get("ip"):
            raise ApiError("Name and IP are required.")
        with db.write() as con:
            if con.execute("SELECT 1 FROM devices WHERE ip=? AND retired=0", (vals["ip"],)).fetchone():
                raise ApiError("A device with that IP exists.")
            con.execute(f"INSERT INTO devices({','.join(vals)}) VALUES ({','.join('?' * len(vals))})", list(vals.values()))
            db.audit(con, g.user["username"], "device_added", vals["name"], {k: v for k, v in vals.items() if k != "commkey"})
        return jsonify(ok=True)

    @app.patch("/api/devices/<int:did>")
    @need("admin")
    def edit_device(did):
        vals = _dev_values(request.get_json() or {})
        with db.write() as con:
            old = con.execute("SELECT * FROM devices WHERE id=?", (did,)).fetchone()
            if not old:
                raise ApiError("Not found.", 404)
            if vals:
                con.execute(f"UPDATE devices SET {', '.join(f'{k}=?' for k in vals)} WHERE id=?", list(vals.values()) + [did])
                db.audit(con, g.user["username"], "device_changed", old["name"],
                         {k: ("***" if k == "commkey" else v) for k, v in vals.items()})
        return jsonify(ok=True)

    @app.post("/api/devices/pull")
    @need("admin")
    def pull_now():
        ids = (request.get_json(silent=True) or {}).get("ids")
        quiet = collector.quiet_until()
        if quiet:
            raise ApiError(f"Quiet window for the Activity Board until {quiet}. Pulls resume after it.", 409)
        collector.request_pull([int(i) for i in ids] if ids else None)
        return jsonify(ok=True)

    @app.get("/api/events")
    @need()
    def events():
        page = max(int(request.args.get("page", 1)), 1)
        kind = request.args.get("kind")
        dev = request.args.get("device")
        where, params = [], []
        if kind:
            where.append("e.kind=?")
            params.append(kind)
        if dev and dev.isdigit():
            where.append("e.device_id=?")
            params.append(int(dev))
        w = ("WHERE " + " AND ".join(where)) if where else ""
        with db.read() as con:
            total = con.execute(f"SELECT COUNT(*) FROM events e {w}", params).fetchone()[0]
            data = rows(con.execute(f"SELECT e.*, d.name AS device FROM events e LEFT JOIN devices d ON d.id=e.device_id "
                                    f"{w} ORDER BY e.id DESC LIMIT 50 OFFSET ?", params + [(page - 1) * 50]))
        return jsonify(rows=data, total=total)

    # ---------- settings, accounts, audit ----------

    @app.get("/api/settings")
    @need()
    def get_settings():
        s = db.get_settings()
        s["quiet_now"] = collector.quiet_until()
        return jsonify(s)

    @app.put("/api/settings")
    @need("admin")
    def put_settings():
        body = request.get_json() or {}
        clean = {}
        if "quiet_windows" in body:
            wins = []
            for w in body["quiet_windows"]:
                if len(w) != 2 or not all(TIME_RE.match(x or "") for x in w) or w[0] == w[1]:
                    raise ApiError("Each quiet window needs a start and an end time (HH:MM), not equal.")
                wins.append([w[0], w[1]])
            clean["quiet_windows"] = sorted(wins)
        for k in ("work_start", "work_end"):
            if k in body:
                if not TIME_RE.match(body[k] or ""):
                    raise ApiError("Times must be HH:MM.")
                clean[k] = body[k]
        if "grace_minutes" in body:
            clean["grace_minutes"] = max(0, min(240, int(body["grace_minutes"])))
        if "weekend" in body:
            clean["weekend"] = sorted({int(d) for d in body["weekend"] if 0 <= int(d) < 7})
        if "enroll_device_id" in body:
            clean["enroll_device_id"] = int(body["enroll_device_id"]) if body["enroll_device_id"] else None
        if "maintenance_time" in body:
            if not TIME_RE.match(body["maintenance_time"] or ""):
                raise ApiError("Times must be HH:MM.")
            if collector.quiet_until(datetime.strptime(body["maintenance_time"], "%H:%M"), clean.get("quiet_windows") or db.get_settings()["quiet_windows"]):
                raise ApiError("Nightly maintenance must be outside the Activity Board windows.")
            clean["maintenance_time"] = body["maintenance_time"]
        if "clock_sync" in body:
            clean["clock_sync"] = bool(body["clock_sync"])
        import json as _json
        with db.write() as con:
            old = db.get_settings(con)
            for k, v in clean.items():
                con.execute("INSERT INTO settings(key, value) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                            (k, _json.dumps(v)))
            db.audit(con, g.user["username"], "settings_changed", None,
                     {k: [old.get(k), v] for k, v in clean.items() if old.get(k) != v})
        return jsonify(ok=True)

    @app.get("/api/accounts")
    @need("admin")
    def accounts():
        with db.read() as con:
            return jsonify(rows=rows(con.execute(
                "SELECT username, role, display_name, locked_until, last_login, created_at FROM accounts ORDER BY username")))

    @app.post("/api/accounts")
    @need("admin")
    def add_account():
        b = request.get_json() or {}
        name = str(b.get("username", "")).strip().lower()
        pw = str(b.get("password", ""))
        role = b.get("role", "hr")
        if not re.match(r"^[a-z0-9._-]{2,40}$", name):
            raise ApiError("Username: 2-40 letters, digits, dot, dash or underscore.")
        if len(pw) < 8 or role not in ROLES:
            raise ApiError("Password needs 8+ characters and a valid role.")
        with db.write() as con:
            if con.execute("SELECT 1 FROM accounts WHERE username=?", (name,)).fetchone():
                raise ApiError("That username exists.")
            con.execute("INSERT INTO accounts(username, pw_hash, role, display_name, created_at) VALUES (?,?,?,?,?)",
                        (name, generate_password_hash(pw), role, str(b.get("display_name", "")).strip(), db.now()))
            db.audit(con, g.user["username"], "account_added", name, {"role": role})
        return jsonify(ok=True)

    @app.patch("/api/accounts/<name>")
    @need("admin")
    def edit_account(name):
        b = request.get_json() or {}
        with db.write() as con:
            if not con.execute("SELECT 1 FROM accounts WHERE username=?", (name,)).fetchone():
                raise ApiError("Not found.", 404)
            if "role" in b:
                if b["role"] not in ROLES:
                    raise ApiError("Unknown role.")
                if name == g.user["username"] and b["role"] != "admin":
                    raise ApiError("You cannot remove your own admin role.")
                con.execute("UPDATE accounts SET role=? WHERE username=?", (b["role"], name))
            if "display_name" in b:
                con.execute("UPDATE accounts SET display_name=? WHERE username=?", (str(b["display_name"]).strip(), name))
            if b.get("password"):
                if len(b["password"]) < 8:
                    raise ApiError("Password needs 8+ characters.")
                con.execute("UPDATE accounts SET pw_hash=?, failed=0, locked_until=NULL WHERE username=?",
                            (generate_password_hash(b["password"]), name))
            if b.get("unlock"):
                con.execute("UPDATE accounts SET failed=0, locked_until=NULL WHERE username=?", (name,))
            db.audit(con, g.user["username"], "account_changed", name,
                     {k: v for k, v in b.items() if k != "password"} | ({"password": "reset"} if b.get("password") else {}))
        return jsonify(ok=True)

    @app.delete("/api/accounts/<name>")
    @need("admin")
    def delete_account(name):
        if name == g.user["username"]:
            raise ApiError("You cannot delete your own account.")
        with db.write() as con:
            con.execute("DELETE FROM accounts WHERE username=?", (name,))
            db.audit(con, g.user["username"], "account_deleted", name)
        return jsonify(ok=True)

    @app.get("/api/audit")
    @need("admin")
    def audit_log():
        page = max(int(request.args.get("page", 1)), 1)
        q = (request.args.get("q") or "").strip()
        where, params = "", []
        if q:
            where = "WHERE username LIKE ? OR action LIKE ? OR target LIKE ? OR detail LIKE ?"
            params = [f"%{q}%"] * 4
        with db.read() as con:
            total = con.execute(f"SELECT COUNT(*) FROM audit {where}", params).fetchone()[0]
            data = rows(con.execute(f"SELECT * FROM audit {where} ORDER BY id DESC LIMIT 50 OFFSET ?",
                                    params + [(page - 1) * 50]))
        return jsonify(rows=data, total=total)

    # ---------- users on devices, device jobs ----------

    @app.get("/api/device-users")
    @need()
    def device_users():
        with db.read() as con:
            devs = rows(con.execute("SELECT id, name, ip, active, last_scan_at, users_on_device, fingers_on_device, "
                                    "faces_on_device FROM devices WHERE retired=0 ORDER BY name"))
            emps = rows(con.execute("SELECT e.id, e.badge, e.emp_no, e.name, e.active, dep.name AS department, "
                                    "(SELECT MAX(ts) FROM punches p WHERE p.badge=e.badge) AS last_punch "
                                    "FROM employees e LEFT JOIN departments dep ON dep.id=e.department_id"))
            cells = rows(con.execute("SELECT device_id, badge, name, privilege, card, has_password, fingers, has_face FROM device_users"))
            backup = {r["badge"]: r["n"] for r in con.execute("SELECT badge, COUNT(*) AS n FROM templates GROUP BY badge")}
            face_backup = {r["badge"] for r in con.execute("SELECT badge FROM faces")}
        by_badge = {}
        for c in cells:
            by_badge.setdefault(c["badge"], {})[str(c["device_id"])] = {
                "fingers": c["fingers"], "name": c["name"], "admin": c["privilege"] == jobs.USER_ADMIN,
                "card": bool(c["card"] and c["card"] != "0"), "password": bool(c["has_password"]),
                "face": bool(c["has_face"])}
        known = set()
        out = []
        for e in emps:
            known.add(e["badge"])
            e["on"] = by_badge.get(e["badge"], {})
            e["backup_fingers"] = backup.get(e["badge"], 0)
            e["backup_face"] = e["badge"] in face_backup
            out.append(e)
        for b, on in by_badge.items():          # users on devices that the system does not know
            if b not in known:
                any_name = next(iter(on.values()))["name"]
                out.append({"id": None, "badge": b, "emp_no": "", "name": any_name, "active": None, "department": None,
                            "last_punch": None, "on": on, "backup_fingers": backup.get(b, 0),
                            "backup_face": b in face_backup, "unknown": True})
        return jsonify(devices=devs, rows=out, enroll_device_id=db.get_settings().get("enroll_device_id"))

    JOB_TITLES = {"scan": "Read users and back up fingerprints", "copy": "Copy employees to devices",
                  "push_names": "Write names to devices", "remove": "Remove employees from devices",
                  "clock": "Set device clocks", "restart": "Restart device"}

    # ---------- one device: the old "Device manage" window ----------

    def _device_or_404(did):
        with db.read() as con:
            d = con.execute("SELECT * FROM devices WHERE id=?", (did,)).fetchone()
        if not d:
            raise ApiError("Not found.", 404)
        return d

    def _queue(kind, params, title):
        jid = jobs.enqueue(kind, params, title, g.user["username"])
        collector.wake()
        return jsonify(id=jid, waiting_for=collector.quiet_until())

    @app.get("/api/devices/<int:did>")
    @need()
    def device_detail(did):
        d = dict(_device_or_404(did))
        d["has_commkey"] = bool(d.pop("commkey"))
        info = json.loads(d.pop("info") or "null")
        if info and "COMKey" in info.get("options", {}):
            info["options"]["COMKey"] = "****"           # never sent to the browser
        with db.read() as con:
            evts = rows(con.execute("SELECT ts, kind, detail FROM events WHERE device_id=? ORDER BY id DESC LIMIT 30", (did,)))
            d["punches_stored"] = con.execute("SELECT COUNT(*) FROM punches WHERE device_id=?", (did,)).fetchone()[0]
        return jsonify(device=d, info=info, events=evts, catalog=devopts.catalog(),
                       actions=jobs.ACTIONS, enroll_device_id=db.get_settings().get("enroll_device_id"))

    @app.post("/api/devices/<int:did>/read")
    @need("admin")
    def device_read(did):
        d = _device_or_404(did)
        return _queue("info", {"device_id": did}, f"Read settings from {d['name']}")

    @app.post("/api/devices/<int:did>/action")
    @need("admin")
    def device_action(did):
        d = _device_or_404(did)
        b = request.get_json() or {}
        a = b.get("action")
        if a not in jobs.ACTIONS:
            raise ApiError("Unknown action.")
        if a in ("initialize", "clear_attlog", "clear_admin") and (b.get("confirm") or "").strip() != d["name"]:
            raise ApiError(f"Type the device name ({d['name']}) to confirm.")
        return _queue("action", {"device_id": did, "action": a}, f"{jobs.ACTIONS[a]}: {d['name']}")

    @app.put("/api/devices/<int:did>/options")
    @need("admin")
    def device_options(did):
        d = _device_or_404(did)
        values = (request.get_json() or {}).get("values") or {}
        if not values:
            raise ApiError("Nothing to change.")
        comm = {k: v for k, v in values.items() if k in devopts.COMM_KEYS}
        other = {k: v for k, v in values.items() if k not in devopts.COMM_KEYS}
        for k, v in values.items():
            try:
                devopts.check_value(k, v)
            except ValueError as e:
                raise ApiError(str(e))
        if comm and other:
            raise ApiError("Save network settings separately.")
        if comm:
            if (request.get_json() or {}).get("confirm", "").strip() != d["name"]:
                raise ApiError(f"Type the device name ({d['name']}) to confirm.")
            if "IPAddress" in comm:
                with db.read() as con:
                    if con.execute("SELECT 1 FROM devices WHERE ip=? AND id<>? AND retired=0", (comm["IPAddress"], did)).fetchone():
                        raise ApiError("Another device already uses that IP.")
            return _queue("comm", {"device_id": did, "values": comm}, f"Change communication settings: {d['name']}")
        return _queue("options", {"device_id": did, "values": other}, f"Change settings: {d['name']}")

    @app.get("/api/enroll/<badge>")
    @need()
    def enroll_info(badge):
        with db.read() as con:
            fids = [r[0] for r in con.execute("SELECT fid FROM templates WHERE badge=? ORDER BY fid", (badge,))]
            face = con.execute("SELECT 1 FROM faces WHERE badge=?", (badge,)).fetchone() is not None
            devs = rows(con.execute("SELECT d.id, d.name, d.active, d.online, "
                                    "(SELECT fingers FROM device_users u WHERE u.device_id=d.id AND u.badge=?) AS fingers "
                                    "FROM devices d WHERE retired=0 ORDER BY name", (badge,)))
        return jsonify(fingers=fids, face=face, devices=devs, enroll_device_id=db.get_settings().get("enroll_device_id"))

    @app.post("/api/enroll")
    @need("admin")
    def enroll_finger():
        b = request.get_json() or {}
        badge = str(b.get("badge") or "").strip()
        try:
            fid = int(b.get("finger"))
        except (TypeError, ValueError):
            fid = -1
        if not badge or not 0 <= fid <= 9:
            raise ApiError("Choose the employee and the finger.")
        dev_id = db.get_settings().get("enroll_device_id")
        if not dev_id:
            raise ApiError("Set the enrollment device in Settings first.")
        with db.read() as con:
            emp = con.execute("SELECT name FROM employees WHERE badge=?", (badge,)).fetchone()
        if not emp:
            raise ApiError("Unknown employee.")
        copy_to = [int(x) for x in b.get("copy_to") or []]
        return _queue("enroll", {"badge": badge, "fid": fid, "device_id": int(dev_id), "copy_to": copy_to},
                      f"Enroll finger {fid} for #{badge} {emp['name']}")

    @app.post("/api/jobs")
    @need("admin")
    def add_job():
        b = request.get_json() or {}
        kind = b.get("kind")
        if kind not in JOB_TITLES:
            raise ApiError("Unknown job.")
        p = {}
        ids = [int(i) for i in b.get("device_ids") or []]
        badges = [str(x) for x in b.get("badges") or []]
        if kind in ("scan", "clock", "push_names", "remove", "restart"):
            p["device_ids"] = ids or None
        if kind == "restart" and len(ids) != 1:
            raise ApiError("Restart one device at a time.")
        if kind in ("copy", "remove") and not badges:
            raise ApiError("Select employees first.")
        if kind == "push_names":
            p["badges"] = badges
        if kind == "copy":
            src = b.get("source")
            if src != "backup" and not str(src).isdigit():
                raise ApiError("Choose where to copy from.")
            targets = [int(t) for t in b.get("targets") or []]
            if not targets:
                raise ApiError("Choose at least one target device.")
            p.update(badges=badges, source=src, targets=targets)
        if kind == "remove":
            p.update(badges=badges, deactivate=bool(b.get("deactivate")))
        n = len(badges)
        title = JOB_TITLES[kind] + (f" ({n} employee{'s' if n != 1 else ''})" if n else "")
        jid = jobs.enqueue(kind, p, title, g.user["username"])
        collector.wake()
        quiet = collector.quiet_until()
        return jsonify(id=jid, waiting_for=quiet)

    @app.get("/api/jobs")
    @need()
    def list_jobs():
        with db.read() as con:
            data = rows(con.execute("SELECT id, kind, title, status, progress, log, created_by, created_at, started_at, "
                                    "finished_at FROM jobs ORDER BY id DESC LIMIT 40"))
        return jsonify(rows=data, quiet_until=collector.quiet_until())

    @app.post("/api/jobs/<int:jid>/cancel")
    @need("admin")
    def cancel_job(jid):
        with db.write() as con:
            n = con.execute("UPDATE jobs SET status='cancelled', finished_at=? WHERE id=? AND status='queued'",
                            (db.now(), jid)).rowcount
            if not n:
                raise ApiError("Only a queued job can be cancelled.")
            db.audit(con, g.user["username"], "job_cancelled", str(jid))
        return jsonify(ok=True)

    @app.get("/api/health")
    def health():
        return jsonify(ok=True)

    # ---------- the React app ----------

    @app.get("/", defaults={"path": ""})
    @app.get("/<path:path>")
    def spa(path):
        if path.startswith("api/"):
            abort(404)
        full = os.path.join(config.SPA_DIR, path)
        if path and os.path.isfile(full):
            resp = send_from_directory(config.SPA_DIR, path)
            if path.startswith("assets/"):
                resp.cache_control.max_age = 31536000
                resp.cache_control.immutable = True
            return resp
        if not os.path.isfile(os.path.join(config.SPA_DIR, "index.html")):
            return "Front end not built.", 503
        resp = send_from_directory(config.SPA_DIR, "index.html")
        resp.cache_control.no_cache = True
        return resp

    return app
