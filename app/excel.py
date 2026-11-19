"""Excel export for a filtered set of punches: Daily Summary, Monthly Grid, All Punches, About."""
from collections import defaultdict
from datetime import date, datetime, time, timedelta
from io import BytesIO

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.cell import WriteOnlyCell
from openpyxl.utils import get_column_letter

from . import db

HEAD_FILL = PatternFill("solid", fgColor="1F3A5F")
HEAD_FONT = Font(bold=True, color="FFFFFF")
LATE_FILL = PatternFill("solid", fgColor="FFF2CC")
SINGLE_FILL = PatternFill("solid", fgColor="F8CBAD")
WEEKEND_FILL = PatternFill("solid", fgColor="EDEDED")
PRESENT_FILL = PatternFill("solid", fgColor="E2EFDA")
THIN = Side(style="thin", color="D9D9D9")
BOX = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)
CENTER = Alignment(horizontal="center")
HEAD_ALIGN = Alignment(horizontal="center", vertical="center", wrap_text=True)
WEEKEND_HEAD = PatternFill("solid", fgColor="7F7F7F")
STATES = {0: "Check-In", 1: "Check-Out", 2: "Break-Out", 3: "Break-In", 4: "OT-In", 5: "OT-Out"}


def _t(s):
    h, m = s.split(":")
    return time(int(h), int(m))


def daily(rows, rules):
    days = defaultdict(list)
    info = {}
    for r in rows:
        ts = datetime.strptime(r["ts"], "%Y-%m-%d %H:%M:%S")
        days[(r["badge"], ts.date())].append((ts, r["device"] or "Manual"))
        info[r["badge"]] = (r["name"], r["department"], r.get("emp_no") or "")
    start, end = _t(rules["work_start"]), _t(rules["work_end"])
    late_after = (datetime.combine(date.today(), start) + timedelta(minutes=int(rules["grace_minutes"]))).time()
    out = {}
    for (badge, d), punches in days.items():
        punches.sort()
        first, last = punches[0][0], punches[-1][0]
        single = len(punches) == 1
        late = first.time() > late_after
        early = (not single) and last.time() < end
        notes = []
        if single:
            notes.append("Single punch")
        if late:
            notes.append(f"Late {_mins(first.time(), start)} min")
        if early:
            notes.append(f"Left early {_mins(end, last.time())} min")
        out[(badge, d)] = {"first": first, "last": None if single else last,
                           "worked": None if single else last - first, "count": len(punches),
                           "devices": ", ".join(sorted({p[1] for p in punches})),
                           "late": late, "early": early, "single": single, "notes": "; ".join(notes),
                           "name": info[badge][0], "department": info[badge][1], "emp_no": info[badge][2]}
    return out


def _mins(a, b):
    return (a.hour * 60 + a.minute) - (b.hour * 60 + b.minute)


def _key(badge):
    return (0, int(badge), "") if badge.isdigit() else (1, 0, badge)


def _num(badge):
    return int(badge) if badge.isdigit() else badge


def _cell(ws, value, fill=None, fmt=None, border=False, center=False):
    c = WriteOnlyCell(ws, value=value)
    if fill:
        c.fill = fill
    if fmt:
        c.number_format = fmt
    if border:
        c.border = BOX
    if center:
        c.alignment = CENTER
    return c


def _sheet(wb, title, titles, widths, freeze="A2"):
    ws = wb.create_sheet(title)
    for i, w in enumerate(widths, start=1):
        ws.column_dimensions[get_column_letter(i)].width = w
    ws.freeze_panes = freeze
    head = []
    for t in titles:
        c = WriteOnlyCell(ws, value=t)
        c.fill, c.font, c.border, c.alignment = HEAD_FILL, HEAD_FONT, BOX, HEAD_ALIGN
        head.append(c)
    ws.append(head)
    return ws


def build(rows, start, end, filters_text=""):
    """rows: punches with badge, ts, state, device, name, department, source, note. Streams (write-only)."""
    rules = db.get_settings()
    weekend = set(rules.get("weekend", []))
    summary = daily(rows, rules)
    wb = Workbook(write_only=True)

    ws = _sheet(wb, "Daily Summary", ["Employee No.", "Device ID", "Name", "Department", "Date", "Day", "First In", "Last Out",
                                      "Worked (h:mm)", "Punches", "Device(s)", "Notes"],
                [12, 10, 28, 14, 12, 11, 10, 10, 13, 9, 22, 30])
    n = 1
    for key in sorted(summary, key=lambda k: (_key(summary[k]["emp_no"] or "999999"), _key(k[0]), k[1])):
        s = summary[key]
        f = SINGLE_FILL if s["single"] else LATE_FILL if (s["late"] or s["early"]) else None
        ws.append([_cell(ws, s["emp_no"], f), _cell(ws, _num(key[0]), f), _cell(ws, s["name"], f), _cell(ws, s["department"], f),
                   _cell(ws, key[1], f, "yyyy-mm-dd"), _cell(ws, key[1].strftime("%A"), f),
                   _cell(ws, s["first"].time(), f, "hh:mm"),
                   _cell(ws, s["last"].time() if s["last"] else None, f, "hh:mm"),
                   _cell(ws, s["worked"].total_seconds() / 86400 if s["worked"] else None, f, "[h]:mm"),
                   _cell(ws, s["count"], f), _cell(ws, s["devices"], f), _cell(ws, s["notes"], f)])
        n += 1
    ws.auto_filter.ref = f"A1:L{n}"

    days = [start + timedelta(days=i) for i in range((end - start).days + 1)]
    if len(days) <= 62:   # a grid wider than two months is not readable
        names = {k[0]: (v["name"], v["department"], v["emp_no"]) for k, v in summary.items()}
        people = sorted(names, key=lambda b: (_key(names[b][2] or "999999"), _key(b)))
        wg = wb.create_sheet("Monthly Grid")
        for i, w in enumerate([12, 10, 28, 14] + [12] * len(days) + [10, 10, 12, 14], start=1):
            wg.column_dimensions[get_column_letter(i)].width = w
        wg.freeze_panes = "E2"
        head = []
        for i, t in enumerate(["Employee No.", "Device ID", "Name", "Department"] + [d.strftime("%d %a") for d in days] +
                              ["Days Present", "Late Days", "Single-Punch Days", "Total Worked (h:mm)"]):
            c = WriteOnlyCell(wg, value=t)
            is_we = 4 <= i < 4 + len(days) and days[i - 4].weekday() in weekend
            c.fill, c.font, c.border, c.alignment = (WEEKEND_HEAD if is_we else HEAD_FILL), HEAD_FONT, BOX, HEAD_ALIGN
            head.append(c)
        wg.append(head)
        for badge in people:
            cells = [_cell(wg, names[badge][2], border=True), _cell(wg, _num(badge), border=True), _cell(wg, names[badge][0], border=True),
                     _cell(wg, names[badge][1], border=True)]
            present = late = single = 0
            total = timedelta()
            for d in days:
                s = summary.get((badge, d))
                if not s:
                    cells.append(_cell(wg, None, WEEKEND_FILL if d.weekday() in weekend else None, border=True))
                    continue
                present += 1
                late += s["late"]
                single += s["single"]
                total += s["worked"] or timedelta()
                text = s["first"].strftime("%H:%M") + ("" if s["single"] else " - " + s["last"].strftime("%H:%M"))
                fill = SINGLE_FILL if s["single"] else LATE_FILL if s["late"] else PRESENT_FILL
                cells.append(_cell(wg, text, fill, border=True, center=True))
            cells += [_cell(wg, present, border=True), _cell(wg, late, border=True), _cell(wg, single, border=True),
                      _cell(wg, total.total_seconds() / 86400, fmt="[h]:mm", border=True)]
            wg.append(cells)

    wp = _sheet(wb, "All Punches", ["Employee No.", "Device ID", "Name", "Department", "Date", "Time", "Day", "Device", "State",
                                    "Source", "Note"], [12, 10, 28, 14, 12, 10, 11, 18, 10, 9, 30])
    for p in rows:
        ts = datetime.strptime(p["ts"], "%Y-%m-%d %H:%M:%S")
        wp.append([p.get("emp_no") or "", _num(p["badge"]), p["name"], p["department"], _cell(wp, ts.date(), fmt="yyyy-mm-dd"),
                   _cell(wp, ts.time(), fmt="hh:mm:ss"), ts.strftime("%A"), p["device"] or "Manual",
                   STATES.get(p["state"], p["state"]), p["source"].title(), p["note"] or ""])
    wp.auto_filter.ref = f"A1:K{len(rows) + 1}"

    wi = wb.create_sheet("About")
    wi.column_dimensions["A"].width = 24
    wi.column_dimensions["B"].width = 70
    for k, v in [
        ("Period", f"{start:%Y-%m-%d} to {end:%Y-%m-%d}"),
        ("Filters", filters_text or "None"),
        ("Generated", datetime.now().strftime("%Y-%m-%d %H:%M")),
        ("Work start", f"{rules['work_start']} (late after {rules['grace_minutes']} min grace)"),
        ("Work end", rules["work_end"]),
        ("Weekend", ", ".join(date(2024, 1, 1 + d).strftime("%A") for d in sorted(weekend)) or "None"),
        ("First In / Last Out", "Earliest and latest punch of the calendar day on any device"),
        ("Yellow", "Late arrival or early leave"),
        ("Red", "Only one punch that day, so no worked time"),
        ("Monthly Grid", "Included for periods up to 62 days"),
        ("Employee No.", "HR's employee number. Device ID is the user number on the attendance devices; they differ"),
        ("Night shifts", "Not handled yet: a shift crossing midnight shows as two days (Phase 3)"),
    ]:
        c = WriteOnlyCell(wi, value=k)
        c.font = Font(bold=True)
        wi.append([c, v])

    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()
