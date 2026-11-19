"""Commands:
  python -m app.manage adduser NAME [--role admin|hr|viewer]
  python -m app.manage passwd NAME
  python -m app.manage import-legacy /data/import/legacy.sqlite
  python -m app.manage backup
  python -m app.manage users
"""
import getpass
import sys

from werkzeug.security import generate_password_hash

from . import collector, db, legacy


def ask_password():
    while True:
        pw = getpass.getpass("Password (8+ characters): ")
        if len(pw) < 8:
            print("Too short.")
        elif pw != getpass.getpass("Again: "):
            print("They do not match.")
        else:
            return pw


def main(argv):
    db.init()
    cmd = argv[0] if argv else ""
    if cmd == "adduser" and len(argv) >= 2:
        name = argv[1].strip().lower()
        role = argv[argv.index("--role") + 1] if "--role" in argv else ("admin" if "--admin" in argv else "hr")
        with db.write() as con:
            con.execute("INSERT INTO accounts(username, pw_hash, role, created_at) VALUES (?,?,?,?) "
                        "ON CONFLICT(username) DO UPDATE SET pw_hash=excluded.pw_hash, role=excluded.role, failed=0, locked_until=NULL",
                        (name, generate_password_hash(ask_password()), role, db.now()))
            db.audit(con, "console", "account_saved", name, {"role": role})
        print(f"Account {name} saved ({role}).")
    elif cmd == "passwd" and len(argv) >= 2:
        with db.write() as con:
            n = con.execute("UPDATE accounts SET pw_hash=?, failed=0, locked_until=NULL WHERE username=?",
                            (generate_password_hash(ask_password()), argv[1].lower())).rowcount
        print("Password changed." if n else "No such account.")
    elif cmd == "import-legacy" and len(argv) >= 2:
        legacy.run(argv[1], "console")
    elif cmd == "backup":
        print(collector.backup_now())
    elif cmd == "users":
        with db.read() as con:
            for r in con.execute("SELECT username, role FROM accounts ORDER BY username"):
                print(r["username"], r["role"])
    else:
        print(__doc__)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
