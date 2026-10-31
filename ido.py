"""Pilote Python pour la montre ID205L (protocole IDO « angelfit »).

Trames de 20 octets max : [commande, clé, données...], écrites sur 0AF6,
réponses en notification sur 0AF7 (et 0AF2 pour les gros transferts).
Entiers en little-endian.
"""

import asyncio
import os
import struct
from datetime import datetime

from bleak import BleakClient, BleakScanner

# Adresse Bluetooth de TA montre (affichée dans Paramètres > À propos sur la montre).
# Sans MONTRE_MAC, la montre est cherchée par son nom Bluetooth.
MAC = os.environ.get("MONTRE_MAC")
NAME = os.environ.get("MONTRE_NOM", "ID205L")
CMD_CHAR = "00000af6-0000-1000-8000-00805f9b34fb"
BIG_CHAR = "00000af1-0000-1000-8000-00805f9b34fb"
NOTIF_CHARS = ["00000af7-0000-1000-8000-00805f9b34fb", "00000af2-0000-1000-8000-00805f9b34fb"]

# commandes
GET, SET, BIND, MSG, APP_CTRL, BLE_CTRL, HEALTH, RESET = 0x02, 0x03, 0x04, 0x05, 0x06, 0x07, 0x08, 0xF0

# types de message (octet bas de 0xF2xx dans le SDK)
MSG_SMS = 0x01

# événements envoyés spontanément par la montre : trame 07 01 <code>
EVENTS = {
    0x01: "music_play", 0x02: "music_pause", 0x03: "music_stop",
    0x04: "music_prev", 0x05: "music_next", 0x06: "photo", 0x07: "photo_burst",
    0x08: "volume_up", 0x09: "volume_down", 0x0A: "camera_open", 0x0B: "camera_close",
    0x0C: "call_answer", 0x0D: "call_reject",
}


def decode_event(data: bytes):
    """Traduit une trame spontanée de la montre en nom d'événement (ou None)."""
    if len(data) >= 3 and data[0] == BLE_CTRL and data[1] == 0x01:
        return EVENTS.get(data[2], f"evt_{data[2]:02x}")
    if len(data) >= 2 and data[0] == BLE_CTRL:
        return {0x02: "find_phone", 0x03: "sos", 0x04: "lost_find", 0x11: "device_operate"}.get(
            data[1], f"ctrl_{data[1]:02x}")
    return None


class Watch:
    def __init__(self, mac=MAC, verbose=False):
        self.mac = mac
        self.verbose = verbose
        self.client = None
        self._waiters = []  # (prefix, future)
        self.listeners = []  # callbacks(bytes) pour les trames non sollicitées

    async def connect(self, timeout=20):
        if self.mac:
            dev = await BleakScanner.find_device_by_address(self.mac, timeout=timeout)
        else:
            dev = await BleakScanner.find_device_by_name(NAME, timeout=timeout)
        if dev is None:
            raise RuntimeError("Montre introuvable : chargeur débranché ? appli du téléphone déconnectée ?")
        self.client = BleakClient(dev)
        await self.client.connect()
        for uuid in NOTIF_CHARS:
            await self.client.start_notify(uuid, self._on_notify)
        return self

    async def disconnect(self):
        if self.client:
            await self.client.disconnect()

    async def __aenter__(self):
        return await self.connect()

    async def __aexit__(self, *exc):
        await self.disconnect()

    def _on_notify(self, sender, data):
        data = bytes(data)
        if self.verbose:
            print(f"<- {sender.uuid[4:8]} {data.hex(' ')}")
        for i, (prefix, fut) in enumerate(self._waiters):
            if data.startswith(prefix) and not fut.done():
                fut.set_result(data)
                del self._waiters[i]
                return
        for cb in self.listeners:
            cb(data)

    async def send(self, cmd, key, payload=b"", reply_prefix=None, timeout=3.0, char=CMD_CHAR):
        """Envoie une trame ; attend la réponse qui commence par reply_prefix (défaut : cmd,key)."""
        frame = bytes([cmd, key]) + bytes(payload)
        assert len(frame) <= 20, "trame > 20 octets"
        frame = frame.ljust(20, b"\x00")
        prefix = bytes([cmd, key]) if reply_prefix is None else reply_prefix
        fut = asyncio.get_running_loop().create_future()
        self._waiters.append((prefix, fut))
        if self.verbose:
            print(f"-> {frame.hex(' ')}")
        await self.client.write_gatt_char(char, frame, response=True)
        try:
            return await asyncio.wait_for(fut, timeout)
        except asyncio.TimeoutError:
            self._waiters = [w for w in self._waiters if w[1] is not fut]
            return None

    # ---------- lecture ----------
    async def device_info(self):
        r = await self.send(GET, 0x01)
        dev_id, ver, mode, bstat, blevel, pair, reboot = struct.unpack_from("<HBBBBBB", r, 2)
        return dict(device_id=dev_id, firmware=ver, mode=mode, battery_status=bstat,
                    battery_level=blevel, paired=pair, rebooted=reboot)

    async def get_time(self):
        r = await self.send(GET, 0x03)
        y, mo, d, h, mi, s, wk = struct.unpack_from("<HBBBBBB", r, 2)
        return datetime(y, mo, d, h, mi, s)

    async def battery(self):
        r = await self.send(GET, 0x05)
        typ, mv, status, level = struct.unpack_from("<BHBB", r, 2)
        return dict(type=typ, voltage_mv=mv, status=status, level=level)

    async def live_data(self):
        """Pas, calories, distance, temps actif, rythme cardiaque du moment."""
        r = await self.send(GET, 0xA0)
        if r is None:
            return None
        step, cal, dist, active, hr = struct.unpack_from("<IIIIB", r.ljust(20, b"\x00"), 2)
        return dict(steps=step, calories=cal, distance=dist, active_time=active, heart_rate=hr)

    # ---------- historique santé (canal 0AF1 -> 0AF2) ----------
    async def health_sync(self, key=0x03, timeout=10):
        """Récupère un historique : 0x03 activité du jour, 0x04 sommeil du jour,
        0x07 cardio du jour, 0x05/0x06/0x08 jours précédents.
        Retourne la liste des paquets bruts (sans l'en-tête 08 key)."""
        packets = []
        done = asyncio.Event()

        def collect(data):
            if data[:2] == bytes([HEALTH, key]):
                packets.append(data[2:])
            elif data[:2] == bytes([HEALTH, 0xEE]):
                done.set()
        self.listeners.append(collect)
        try:
            await self.send(HEALTH, 0x01, b"\x01\x00", char=BIG_CHAR)
            first = await self.send(HEALTH, key, b"\x01\x00\x00", char=BIG_CHAR)
            if first:
                packets.insert(0, first[2:])
                try:
                    await asyncio.wait_for(done.wait(), timeout)
                except asyncio.TimeoutError:
                    pass
            await self.send(HEALTH, 0x02, char=BIG_CHAR)
        finally:
            self.listeners.remove(collect)
        return packets

    async def day_activity(self):
        """Pas/calories/distance du jour par tranche (l'en-tête donne la date et l'intervalle)."""
        p = await self.health_sync(0x03)
        if not p:
            return None
        head = p[0]
        y, mo, d = struct.unpack_from("<HBB", head, 2)
        samples = b"".join(x[2:] for x in p[1:])
        return dict(date=f"{y}-{mo:02d}-{d:02d}", header=head.hex(" "),
                    nonzero=any(samples), raw=samples.hex())

    # ---------- capteurs bruts (mode test usine) ----------
    async def test_mode(self, on=True):
        """Mode test usine. En sortir redémarre la montre (la connexion BLE se coupe)."""
        return await self.send(0xAA, 0x01 if on else 0x02, timeout=3)

    async def accel(self):
        """Une mesure de l'accéléromètre (x, y, z) — nécessite test_mode(True)."""
        r = await self.send(0xAA, 0x03, timeout=3)
        if r is None or len(r) < 9:
            return None
        return struct.unpack_from("<hhh", r, 3)

    # ---------- réglages ----------
    async def set_time(self, t=None):
        t = t or datetime.now()
        payload = struct.pack("<HBBBBBB", t.year, t.month, t.day, t.hour, t.minute, t.second, t.weekday())
        return await self.send(SET, 0x01, payload)

    async def bind(self):
        """Appairage logique (os=1 Android) : certaines fonctions l'exigent."""
        return await self.send(BIND, 0x01, bytes([0x01, 0x00, 0x00, 0x00]))

    async def enable_notifications(self, on=True):
        # notify_switch 0xAA = on / 0x55 = off ; items = tout ; appels on, délai 3 s
        sw = 0xAA if on else 0x55
        return await self.send(SET, 0x30, bytes([sw, 0xFF, 0xFF, sw, 0x03]))

    async def vibrate(self, seconds=1):
        return await self.send(SET, 0x53, struct.pack("<BH", 1, int(seconds * 1000)))

    async def find_device(self):
        return await self.send(APP_CTRL, 0x04, b"\x01")

    async def raise_to_wake(self, on=True, seconds=5):
        return await self.send(SET, 0x28, bytes([0xAA if on else 0x55, seconds]))

    async def heart_rate_mode(self, mode):
        """0x88 auto, 0xAA manuel, 0x55 off (valeurs du SDK)."""
        return await self.send(SET, 0x25, bytes([mode]))

    async def realtime_sensors(self, accel=True, heart=True):
        """Active le flux brut accéléromètre / capteur cardiaque."""
        return await self.send(SET, 0x52, bytes([1 if accel else 0, 1 if heart else 0]))

    # ---------- épuration : couper ce qui ne sert pas ----------
    async def long_sit_reminder(self, on=False, start=(9, 0), end=(18, 0), interval_min=60):
        """Rappel « tu es assis depuis trop longtemps » (repetitions = jours, 0x7F = tous)."""
        rep = 0x7F if on else 0x00
        payload = struct.pack("<BBBBHH", start[0], start[1], end[0], end[1], interval_min, rep)
        return await self.send(SET, 0x20, payload)

    async def anti_lost(self, on=False):
        return await self.send(SET, 0x21, bytes([0x01 if on else 0x00]))

    async def do_not_disturb(self, on=True, start=(22, 0), end=(7, 0)):
        return await self.send(SET, 0x29, bytes([0xAA if on else 0x55, start[0], start[1], end[0], end[1]]))

    async def weather(self, on=False):
        return await self.send(SET, 0x2D, bytes([0xAA if on else 0x55]))

    async def landscape(self, on=False):
        return await self.send(SET, 0x2B, bytes([0x01 if on else 0x02]))

    async def sport_modes(self, *names):
        """Ne garde que les sports cités dans le menu Sport (ex. 'run', 'walk')."""
        order = ["walk", "run", "bike", "on_foot", "swim", "climbing", "badminton", "other",
                 "fitness", "spinning", "ellipsoid", "treadmill", "sit_up", "push_up", "dumbbell",
                 "weightlifting", "bodybuilding", "yoga", "rope", "table_tennis", "basketball",
                 "football", "volleyball", "tennis", "golf", "baseball", "skiing", "roller", "dance"]
        bits = 0
        for n in names:
            bits |= 1 << order.index(n)
        return await self.send(SET, 0x2E, bits.to_bytes(4, "little"))

    async def music_menu(self, on=True):
        """Active l'écran musique : ses 4 touches deviennent des boutons pour ton programme."""
        # trames relevées dans VeryFit Pro : 03 2a aa 55 puis 06 01 00 00 00 00
        await self.send(SET, 0x2A, bytes([0xAA, 0x55]) if on else bytes([0x55, 0x55]))
        return await self.send(APP_CTRL, 0x01, bytes([0x00 if on else 0x01, 0, 0, 0]))

    async def camera_mode(self, on=True):
        """Ouvre l'écran « appareil photo » : chaque appui envoie l'événement 'photo'."""
        return await self.send(APP_CTRL, 0x02, bytes([0x00 if on else 0x01]))

    async def reboot(self):
        return await self.send(RESET, 0x01)

    # ---------- affichage ----------
    async def _send_chunked(self, key, body):
        """Découpe body en paquets de 16 octets : [05, key, total, n°, 16 octets]."""
        chunks = [body[i:i + 16] for i in range(0, len(body), 16)] or [b""]
        total = len(chunks)
        for serial, chunk in enumerate(chunks, 1):
            payload = bytes([total, serial]) + chunk.ljust(16, b"\x00")
            r = await self.send(MSG, key, payload, reply_prefix=bytes([MSG, key]))
            if r is None:
                return False
        return True

    async def message(self, title, text, kind=MSG_SMS, number=""):
        """Affiche une notification « title / text » sur l'écran."""
        t, x, n = title.encode()[:30], text.encode()[:150], number.encode()[:20]
        body = bytes([kind, len(x), len(n), len(t)]) + n + t + x
        return await self._send_chunked(0x03, body)

    async def call(self, name, number=""):
        """Affiche un appel entrant (nom + numéro)."""
        nm, n = name.encode()[:30], number.encode()[:20]
        body = bytes([len(n), len(nm)]) + n + nm
        return await self._send_chunked(0x01, body)

    async def call_end(self):
        return await self.send(MSG, 0x02, b"\x01")
