"""Sonde les commandes de la montre : envoie [groupe, clé] sur 0AF6 et note les réponses.

Usage : python sonde.py <groupe_hex> [debut_hex] [fin_hex] [--pad]
Ex.   : python sonde.py 02 00 30
On ne sonde que des groupes de lecture : un groupe inconnu peut déclencher
une remise à zéro ou une mise à jour du firmware.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # accès à ido.py
import asyncio
import sys

from bleak import BleakClient

from montre_ble import find_watch, hexdump, log

CMD = "00000af6-0000-1000-8000-00805f9b34fb"
NOTIF = ["00000af7-0000-1000-8000-00805f9b34fb", "00000af2-0000-1000-8000-00805f9b34fb"]


async def main():
    args = [a for a in sys.argv[1:] if a != "--pad"]
    pad = "--pad" in sys.argv
    group = int(args[0], 16)
    start = int(args[1], 16) if len(args) > 1 else 0x00
    end = int(args[2], 16) if len(args) > 2 else 0x20

    dev = await find_watch()
    if dev is None:
        log("Montre introuvable (chargeur débranché ?)")
        return

    replies = []

    def handler(sender, data):
        replies.append((sender.uuid[4:8], bytes(data)))

    async with BleakClient(dev) as client:
        for uuid in NOTIF:
            await client.start_notify(uuid, handler)
        for key in range(start, end + 1):
            cmd = bytes([group, key])
            if pad:
                cmd = cmd.ljust(20, b"\x00")
            replies.clear()
            await client.write_gatt_char(CMD, cmd, response=True)
            await asyncio.sleep(0.8)
            if replies:
                for src, data in replies:
                    log(f"{group:02x} {key:02x} -> {src} : {hexdump(data)}")
            else:
                log(f"{group:02x} {key:02x} -> (rien)")


if __name__ == "__main__":
    asyncio.run(main())
