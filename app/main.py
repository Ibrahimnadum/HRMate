"""Start: migrate the database, seed devices on first run, start the collector, serve with Waitress."""
import logging
import os

from waitress import serve

from . import collector, config, db, legacy
from .web import create_app

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
logging.getLogger("waitress.queue").setLevel(logging.ERROR)


def main():
    os.makedirs(config.DATA_DIR, exist_ok=True)
    db.init()
    legacy.seed_devices_from_file(os.environ.get("DEVICES_FILE", "/config/devices.txt"))
    collector.start()
    serve(create_app(), host="0.0.0.0", port=config.PORT, threads=6)


if __name__ == "__main__":
    main()
