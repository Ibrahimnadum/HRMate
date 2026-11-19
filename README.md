# Iratec Attendance

Attendance system for the ZKTeco devices (iFace 1000 / 950 Plus) at Iratec, running on the Synology NAS.

- **Web:** `http://192.168.5.18:8090` — React front end (`web/`) over a Flask JSON API (`app/`), SQLite in `data/`.
- **Collector:** checks port 4370 every minute and pulls logs every 10 minutes, never inside the
  **Activity Board windows** (Settings), and never deletes anything from a device.
- **History:** the old Attendance Management database is converted with `tools/convert_mdb.py` and imported
  with `deploy-nas.ps1 -ImportLegacy` (safe to repeat).
- **Backups:** nightly at 04:00 to `data/backups`, 30 kept (gzip).

## Layout
```
app/        Python service: api (web.py), collector, excel, legacy import, db + migrations
web/        React + TypeScript (Vite); built inside the Docker image
tools/      convert_mdb.py  (att2000.mdb -> legacy.sqlite)
config/     devices.txt (only fills an empty device list on first start)
scripts/    deploy-nas.ps1, add-user.ps1
```

## Deploy
```powershell
.\scripts\deploy-nas.ps1                 # copy + rebuild
.\scripts\deploy-nas.ps1 -ImportLegacy   # + import import\legacy.sqlite
```

## Develop
```
DATA_DIR=./data PORT=18090 python -m app.main     # API on :18090
cd web && npm install && npm run dev               # front end on :5173, proxies /api
```

## Roles
admin (everything) · hr (employees, departments, manual punches, export) · viewer (view, export)

## Phases
1. Foundation (this) · 2. Device management · 3. Shifts, holidays, absence · 4. Reports · 5. Alerts and cut-over
