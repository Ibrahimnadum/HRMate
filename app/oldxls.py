"""The export of the old Attendance Management program ("Search Employee's Attendance Checking Record" -> Export),
reproduced byte for byte in layout: the same old .xls (BIFF) format, the same nine text columns, the same order,
so HR's existing Excel formulas keep working.

Columns: Department | Name | No. | Date/Time | Status | Location ID | ID Number | Workcode | CardNo
  No.        = user number on the devices        ID Number = HR employee number, as written (e.g. 0002)
  Date/Time  = text, M/D/YYYY h:mm:ss AM          Status    = C/In, C/Out, ...
Rows: by department (old department order), then device user number, then time.
"""
import struct
from datetime import datetime
from io import BytesIO

COLUMNS = ["Department", "Name", "No.", "Date/Time", "Status", "Location ID", "ID Number", "Workcode", "CardNo"]
STATUS = {0: "C/In", 1: "C/Out", 2: "Out", 3: "Out Back", 4: "OT In", 5: "OT Out"}
WIDTHS = [0x14, 0x14, 0x14, 0x13, 0x14, 0x06, 0x14, 0x14, 0x14]

# Header records copied from a file the old program wrote: BOF, fonts, footer, number formats, column XFs.
_FONT = b"\xc8\x00\x00\x00\x05Arial"
_HEAD = [
    (0x0809, b"\x00\x00\x10\x00\x00\x00"),
    None,                                   # DIMENSIONS, filled in per file
    (0x0031, _FONT), (0x0031, _FONT), (0x0031, b"\xc8\x00\x01\x00\x05Arial"),
    (0x0015, b"\rPage &P of &N"),
    (0x001E, b"\x07General"), (0x001E, b"\t#,###,##0"), (0x001E, b"\x0c#,###,##0.00"), (0x001E, b"\x08M/d/yyyy"),
    (0x001E, b"\th:mm AMPM"), (0x001E, b"\x12M/d/yyyy h:mm AMPM"), (0x001E, b"\x0600.00$"),
    (0x0043, b"\x01\x00@\x00"), (0x0043, b"\x02\x00@\x00"), (0x0043, b"\x01\x00A\x00"), (0x0043, b"\x01\x00B\x00"),
    (0x0043, b"\x01\x00C\x00"), (0x0043, b"\x01\x00D\x00"), (0x0043, b"\x01\x00E\x00"), (0x0043, b"\x01\x00F\x00"),
]


def _rec(kind, data):
    return struct.pack("<HH", kind, len(data)) + data


def _label(row, col, text, head=False):
    raw = str(text if text is not None else "").encode("cp1252", errors="replace")[:255]
    attr = b"A\x00\x00" if head else b"@\x00\x00"
    return _rec(0x0004, struct.pack("<HH", row, col) + attr + bytes([len(raw)]) + raw)


def old_datetime(ts):
    d = datetime.strptime(ts, "%Y-%m-%d %H:%M:%S")
    hour = d.hour % 12 or 12
    return f"{d.month}/{d.day}/{d.year} {hour}:{d.minute:02d}:{d.second:02d} {'AM' if d.hour < 12 else 'PM'}"


def _values(r):
    return [r["department"], r["name"], r["badge"], old_datetime(r["ts"]),
            STATUS.get(r["state"], "C/In" if r["state"] is None else str(r["state"])),
            r["location"] or "", r["emp_no"] or "", "0", r["card"] or ""]


def build(rows, sheet="Sheet1"):
    """Same columns, text and order as the old export, written as an Excel 97-2003 workbook (BIFF8).
    The old program's own format (BIFF2) opens read-only in Protected View in current Excel, so HR could not edit it."""
    import xlwt
    wb = xlwt.Workbook(encoding="utf-8")
    ws = wb.add_sheet((sheet or "Sheet1")[:31])
    font = xlwt.Font()
    font.name, font.height = "Arial", 200
    style = xlwt.XFStyle()
    style.font = font
    style.num_format_str = "@"                          # every cell is text, as in the old file
    for c, name in enumerate(COLUMNS):
        ws.write(0, c, name, style)
        ws.col(c).width = WIDTHS[c] * 256
    for i, r in enumerate(rows, start=1):
        for c, v in enumerate(_values(r)):
            ws.write(i, c, str(v), style)
    out = BytesIO()
    wb.save(out)
    return out.getvalue()


def build_biff2(rows):
    """The old program's exact bytes (BIFF2). Kept in case a tool needs the original format.
    rows: dicts with department, name, badge, ts, state, location, emp_no, card (already in the old order)."""
    out = [_rec(*r) for r in _HEAD if r]
    out.insert(1, _rec(0x0200, struct.pack("<HHHHH", 0, len(rows) + 1, 0, len(COLUMNS), 0)))
    for c, name in enumerate(COLUMNS):
        out.append(_label(0, c, name, head=True))
    for i, r in enumerate(rows, start=1):
        for c, v in enumerate(_values(r)):
            out.append(_label(i, c, v))
    for c, w in enumerate(WIDTHS):
        out.append(_rec(0x0024, struct.pack("<BBH", c, c, w << 8)))
    out.append(_rec(0x000A, b""))
    return b"".join(out)
