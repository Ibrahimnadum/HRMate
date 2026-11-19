"""What the device pages read and may write.

Every key in OPTIONS is read on "Read device"; a key the firmware does not have is simply missing from the result,
so the page shows only what this device really supports. `edit` says how a value may be changed; keys whose exact
meaning on iFace firmware 6.60 is not confirmed yet are read-only (edit=None) until we compare them with the old
program's "Read Options".
"""

DATE_FORMATS = {"0": "YY-MM-DD", "1": "YY/MM/DD", "2": "YY.MM.DD", "3": "MM-DD-YY", "4": "MM/DD/YY",
                "5": "MM.DD.YY", "6": "DD-MM-YY", "7": "DD/MM/YY", "8": "DD.MM.YY", "9": "YYYYMMDD"}

# key: (tab, label, edit)  edit = None | "bool" | ("int", lo, hi) | ("choice", {value: label}) | "ip"
OPTIONS = {
    # Device Info
    "~DeviceName": ("info", "Product name", None),
    "~SerialNumber": ("info", "Serial number", None),
    "~Platform": ("info", "Platform", None),
    "~ProductTime": ("info", "Manufacture time", None),
    "~ZKFPVersion": ("info", "Fingerprint version", None),
    "ZKFaceVersion": ("info", "Face version", None),
    "FaceFunOn": ("info", "Face function", None),
    "~OEMVendor": ("info", "Vendor", None),
    "MAC": ("info", "MAC address", None),
    "Language": ("info", "Language code", None),
    # Advanced Function
    "DtFmt": ("advanced", "Date format", ("choice", DATE_FORMATS)),
    "VoiceOn": ("advanced", "Voice prompts", "bool"),
    "AudioVol": ("advanced", "Volume", None),
    # Power
    "IdleMinute": ("power", "Idle after (minutes, 0 = never)", ("int", 0, 999)),
    "IdlePower": ("power", "When idle", None),
    "LockPowerButton": ("power", "Lock power button", None),
    "LockPWRButton": ("power", "Lock power button", None),
    "AutoPowerOff": ("power", "Scheduled power off", None),
    "AutoPowerOn": ("power", "Scheduled power on", None),
    "AutoPowerSuspend": ("power", "Scheduled sleep", None),
    # Comm Set
    "IPAddress": ("comm", "IP address", "ip"),
    "NetMask": ("comm", "Subnet mask", "ip"),
    "GATEIPAddress": ("comm", "Gateway", "ip"),
    "DeviceID": ("comm", "Machine number", ("int", 1, 254)),
    "COMKey": ("comm", "Comm key", ("int", 0, 999999)),
    "DHCP": ("comm", "DHCP", None),
    "TCPPort": ("comm", "TCP port", None),
    "UDPPort": ("comm", "UDP port", None),
    "RS232BaudRate": ("comm", "RS232 baud rate", None),
    "RS232On": ("comm", "RS232", None),
    "RS485On": ("comm", "RS485", None),
}

COMM_KEYS = {"IPAddress", "NetMask", "GATEIPAddress", "DeviceID", "COMKey"}

# free-sizes reply: index -> meaning (the SDK's GetDeviceStatus order, as the old program shows it)
SIZE_FIELDS = {4: "users", 6: "fingers", 8: "records", 10: "super_logs", 12: "admins", 13: "passwords",
               14: "fingers_cap", 15: "users_cap", 16: "records_cap", 17: "fingers_free", 18: "users_free",
               19: "records_free", 20: "faces", 21: "faces_free", 22: "faces_cap"}


def check_value(key, value):
    """Validated text value for writing, or raises ValueError with a readable reason."""
    spec = OPTIONS.get(key)
    if not spec or spec[2] is None:
        raise ValueError(f"{key} cannot be changed from here yet.")
    edit = spec[2]
    v = str(value).strip()
    if edit == "bool":
        if v not in ("0", "1"):
            raise ValueError(f"{spec[1]} must be on or off.")
    elif edit == "ip":
        parts = v.split(".")
        if len(parts) != 4 or not all(p.isdigit() and 0 <= int(p) <= 255 for p in parts):
            raise ValueError(f"{spec[1]} looks wrong.")
    elif edit[0] == "int":
        if not v.isdigit() or not edit[1] <= int(v) <= edit[2]:
            raise ValueError(f"{spec[1]} must be a number from {edit[1]} to {edit[2]}.")
        v = str(int(v))
    elif edit[0] == "choice":
        if v not in edit[1]:
            raise ValueError(f"{spec[1]}: unknown choice.")
    return v


def catalog():
    out = []
    for k, (tab, label, edit) in OPTIONS.items():
        e = None
        if edit == "bool" or edit == "ip":
            e = {"type": edit}
        elif edit:
            e = {"type": edit[0]}
            if edit[0] == "int":
                e.update(min=edit[1], max=edit[2])
            else:
                e["choices"] = edit[1]
        out.append({"key": k, "tab": tab, "label": label, "edit": e})
    return out
