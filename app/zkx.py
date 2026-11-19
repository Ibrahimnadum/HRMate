"""pyzk with the extra ZKTeco commands the old "Device manage" window uses.

pyzk keeps its socket helpers private (name-mangled as _ZK__...), so they are reached through those names.
Every option read goes through `option()`, which never raises for a key the firmware does not know.
"""
from socket import timeout as SocketTimeout
from struct import pack, unpack

from zk import ZK, const
from zk.exception import ZKErrorResponse

CMD_CLEAR_ADMIN = 20
CMD_CLEAR_OPLOG = 33
CMD_REFRESHOPTION = 1014
CMD_GET_FACE = 0x96          # same commands the SDK uses for GetUserFaceStr / SetUserFaceStr / DelUserFace
CMD_SET_FACE = 0x97
CMD_DEL_FACE = 0x98
FACE_INDEX = 50


class EnrollFailed(Exception):
    pass


class ZKX(ZK):
    # ---------- options ----------

    def option(self, key):
        """Value of one device option as text, or None when the firmware does not have it."""
        r = self._ZK__send_command(const.CMD_OPTIONS_RRQ, key.encode() + b"\x00", 1024)
        if not r.get("status"):
            try:
                self._clear_error(key.encode() + b"\x00")
            except Exception:
                pass
            return None
        data = self._ZK__data
        if b"=" not in data:
            return None
        return data.split(b"=", 1)[1].split(b"\x00")[0].decode(errors="replace").strip()

    def set_option(self, key, value):
        r = self._ZK__send_command(const.CMD_OPTIONS_WRQ, f"{key}={value}".encode() + b"\x00", 1024)
        if not r.get("status"):
            raise ZKErrorResponse(f"The device refused {key}={value}")
        return True

    def refresh_options(self):
        return bool(self._ZK__send_command(CMD_REFRESHOPTION).get("status"))

    # ---------- counters ----------

    def sizes_raw(self):
        """All integers of the free-sizes reply (the first 20 are counters and capacities, the rest faces)."""
        r = self._ZK__send_command(const.CMD_GET_FREE_SIZES, b"", 1024)
        if not r.get("status"):
            raise ZKErrorResponse("Can't read sizes")
        data = self._ZK__data
        n = len(data) // 4
        return list(unpack(f"<{n}i", data[:n * 4]))

    # ---------- maintenance ----------

    def clear_admin(self):
        if not self._ZK__send_command(CMD_CLEAR_ADMIN).get("status"):
            raise ZKErrorResponse("The device refused to clear admin rights")
        return True

    def clear_oplog(self):
        if not self._ZK__send_command(CMD_CLEAR_OPLOG).get("status"):
            raise ZKErrorResponse("The device refused to clear the super log")
        return True

    # ---------- faces ----------

    @staticmethod
    def _face_key(user_id, index):
        uid = str(user_id).encode()[:24]
        return uid + b"\x00" * (24 - len(uid))  + bytes([0, index])

    def get_face(self, user_id, index=FACE_INDEX):
        """The user's face template as bytes, or None when the user has no face on this device."""
        r = self._ZK__send_command(CMD_GET_FACE, self._face_key(user_id, index) + b"\x00\x00", 1024 + 8)
        if self._ZK__response not in (const.CMD_PREPARE_DATA, const.CMD_DATA):
            return None
        data = self._ZK__recieve_chunk()
        return bytes(data) if data else None

    def set_face(self, user_id, template, index=FACE_INDEX):
        """Write a face template for a user that already exists on the device."""
        self._send_with_buffer(template)
        r = self._ZK__send_command(CMD_SET_FACE, self._face_key(user_id, index) + pack("<H", len(template)))
        ok = r.get("status")
        try:
            self.free_data()
        except Exception:
            pass
        if not ok:
            raise ZKErrorResponse(f"The device refused the face for #{user_id} (code {r.get('code')})")
        return True

    def delete_face(self, user_id, index=FACE_INDEX):
        return bool(self._ZK__send_command(CMD_DEL_FACE, self._face_key(user_id, index) + b"\x00\x00").get("status"))

    # ---------- remote enrollment ----------

    def enroll_finger(self, user_id, fid, say, wait=60):
        """Put the device in enrollment mode for one finger and follow the presses.

        The device answers with real-time events; the event type is in the packet's session field:
        EF_FINGER (finger on the sensor), EF_FPFTR (quality score 0-100 of a press), EF_ENROLLFINGER (result:
        0 saved, 5 already enrolled, 4/6 timeout or cancelled). Old firmware without types sends 0x64 per good press.
        `say(text)` is called at every step. Raises EnrollFailed when nothing is saved.
        """
        sock = self._ZK__sock
        old_timeout = sock.gettimeout()

        def event():
            data = sock.recv(1032)
            self._ZK__ack_ok()
            if len(data) < 16:
                return None, 0, b""
            cmd, _, ev, _ = unpack("<4H", data[8:16])
            payload = data[16:]
            val = unpack("<H", payload[:2].ljust(2, b"\x00"))[0]
            return (ev if cmd == const.CMD_REG_EVENT else None), val, payload

        self.cancel_capture()
        try:
            self.reg_event(const.EF_FINGER | const.EF_ENROLLFINGER | const.EF_FPFTR)
        except Exception:
            pass
        r = self._ZK__send_command(const.CMD_STARTENROLL, pack("<24sbb", str(user_id).encode(), fid, 1))
        if not r.get("status"):
            raise EnrollFailed("The device did not accept the enrollment command")
        presses = 0
        try:
            sock.settimeout(wait)
            say("Waiting for press 1 of 3 ...")
            while True:
                ev, val, payload = event()
                if ev == const.EF_ENROLLFINGER:
                    if val == 0:
                        return
                    if val == 5:
                        raise EnrollFailed("This finger is already enrolled for another person on the device")
                    if val in (4, 6):
                        raise EnrollFailed("Timed out or cancelled on the device")
                    raise EnrollFailed(f"The device did not save the fingerprint (code {val}). Try again.")
                if ev == const.EF_FPFTR or (ev is None and val == 0x64):
                    presses += 1
                    score = payload[0] if payload else val
                    say(f"Press {presses} read (quality {score})" + (f". Waiting for press {presses + 1} ..." if presses < 3 else ". Saving ..."))
                    continue
                if ev == const.EF_FINGER:
                    continue
                if ev is None and val in (4, 6):
                    raise EnrollFailed("Timed out or cancelled on the device")
                if ev is None and val == 0 and presses >= 3:
                    return
                say(f"(device event {ev}, data {payload[:6].hex()})")
        except SocketTimeout:
            if presses:
                raise EnrollFailed(f"Stopped after press {presses}: no further press within {wait} seconds")
            raise EnrollFailed(f"Nobody pressed the finger within {wait} seconds")
        finally:
            sock.settimeout(old_timeout)
            for fn in (lambda: self.reg_event(0), self.cancel_capture, self.verify_user):
                try:
                    fn()
                except Exception:
                    pass
