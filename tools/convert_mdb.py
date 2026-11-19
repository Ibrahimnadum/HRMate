"""Convert the old ZKTeco Attendance Management database (att2000.mdb) into a small SQLite file
that the service imports with:  python -m app.manage import-legacy /data/import/legacy.sqlite

Run on any PC with Python:  pip install access-parser
                            python tools/convert_mdb.py att2000.mdb legacy.sqlite
"""
import sqlite3
import sys

from access_parser import AccessParser


def table(db, name):
    d = db.parse_table(name)
    cols = list(d)
    n = len(d[cols[0]]) if cols else 0
    return [{c: d[c][i] for c in cols} for i in range(n)]


def clean_ts(v):
    if not v or not str(v)[:1].isdigit():
        return None
    return str(v)[:19]


def main(src, dst):
    db = AccessParser(src)
    out = sqlite3.connect(dst)
    out.executescript("""
    DROP TABLE IF EXISTS departments; DROP TABLE IF EXISTS users; DROP TABLE IF EXISTS machines;
    DROP TABLE IF EXISTS punches; DROP TABLE IF EXISTS corrections;
    CREATE TABLE departments (id INTEGER, parent INTEGER, name TEXT);
    CREATE TABLE users (id INTEGER, badge TEXT, name TEXT, dept INTEGER, title TEXT, gender TEXT, card TEXT, emp_no TEXT, phone TEXT);
    CREATE TABLE machines (number INTEGER, alias TEXT, ip TEXT, port INTEGER, commkey TEXT, serial TEXT, enabled INTEGER);
    CREATE TABLE punches (userid INTEGER, ts TEXT, type TEXT, verify INTEGER, sensor TEXT, serial TEXT);
    CREATE TABLE corrections (userid INTEGER, ts TEXT, reason TEXT, by TEXT, at TEXT);
    """)
    out.executemany("INSERT INTO departments VALUES (?,?,?)",
                    [(r["DEPTID"], r["SUPDEPTID"], r["DEPTNAME"]) for r in table(db, "DEPARTMENTS")])
    # SSN holds the real employee number (HR's ID); Badgenumber is the user ID on the devices.
    out.executemany("INSERT INTO users VALUES (?,?,?,?,?,?,?,?,?)",
                    [(r["USERID"], str(r["Badgenumber"] or "").strip(), (r["Name"] or "").strip(), r["DEFAULTDEPTID"],
                      (r.get("TITLE") or "").strip(), (r.get("Gender") or "").strip(), (r.get("CardNo") or "").strip(),
                      (r.get("SSN") or "").strip(), (r.get("PAGER") or "").strip())
                     for r in table(db, "USERINFO")])
    out.executemany("INSERT INTO machines VALUES (?,?,?,?,?,?,?)",
                    [(r["MachineNumber"], r["MachineAlias"], r["IP"], r["Port"], r["CommPassword"], r["sn"],
                      1 if r["Enabled"] else 0) for r in table(db, "Machines")])
    c = db.parse_table("CHECKINOUT")
    rows = []
    for i in range(len(c["USERID"])):
        ts = clean_ts(c["CHECKTIME"][i])
        if ts:
            rows.append((c["USERID"][i], ts, c["CHECKTYPE"][i], c["VERIFYCODE"][i], c["SENSORID"][i],
                         (c["sn"][i] or "").strip() or None))
    out.executemany("INSERT INTO punches VALUES (?,?,?,?,?,?)", rows)
    out.executemany("INSERT INTO corrections VALUES (?,?,?,?,?)",
                    [(r["USERID"], clean_ts(r["CHECKTIME"]), (r["YUYIN"] or "").strip(), r["MODIFYBY"],
                      clean_ts(r["DATE"])) for r in table(db, "CHECKEXACT")])
    out.commit()
    for t in ("departments", "users", "machines", "punches", "corrections"):
        print(t, out.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0])
    out.execute("VACUUM")
    out.close()


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
