"""Process settings from environment variables. Everything HR can change lives in the settings table."""
import os

DATA_DIR = os.environ.get("DATA_DIR", "/data")
DB_PATH = os.path.join(DATA_DIR, "attendance.sqlite3")
BACKUP_DIR = os.path.join(DATA_DIR, "backups")
IMPORT_DIR = os.path.join(DATA_DIR, "import")
SPA_DIR = os.environ.get("SPA_DIR", os.path.join(os.path.dirname(__file__), "spa"))

PULL_MINUTES = int(os.environ.get("PULL_MINUTES", "10"))
CHECK_SECONDS = int(os.environ.get("CHECK_SECONDS", "60"))
DOWN_AFTER = int(os.environ.get("DOWN_AFTER", "2"))      # failed checks in a row before "offline"
PULL_TIMEOUT = int(os.environ.get("PULL_TIMEOUT", "30"))
BACKUP_KEEP = int(os.environ.get("BACKUP_KEEP", "30"))
BACKUP_HOUR = int(os.environ.get("BACKUP_HOUR", "4"))     # local hour for the nightly backup
PORT = int(os.environ.get("PORT", "8000"))
