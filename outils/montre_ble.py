"""Outil de reverse engineering BLE pour la montre ID205L.

Usage :
    python montre_ble.py scan       # cherche la montre et affiche les pubs BLE
    python montre_ble.py explore    # se connecte, liste services/caractéristiques,
                                    # lit tout ce qui est lisible, écoute les notifs
    python montre_ble.py shell      # console : envoie des octets hex, affiche les réponses

Tout est aussi journalisé dans montre_log.txt.
Pense à débrancher le chargeur (le Bluetooth se coupe pendant la charge)
et à déconnecter la montre de l'appli du téléphone.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # accès à ido.py
import asyncio
import sys
from datetime import datetime

from bleak import BleakClient, BleakScanner

from ido import MAC, NAME
LOG_FILE = "montre_log.txt"
SCAN_TIMEOUT = 15.0


def log(msg):
    line = f"[{datetime.now():%H:%M:%S.%f}"[:-3] + f"] {msg}"
    print(line)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def hexdump(data: bytes) -> str:
    h = data.hex(" ")
    ascii_ = "".join(chr(b) if 32 <= b < 127 else "." for b in data)
    return f"{h}  |{ascii_}|"


async def find_watch():
    log(f"Scan BLE ({SCAN_TIMEOUT:.0f}s) à la recherche de {MAC or NAME}...")
    found = await BleakScanner.discover(timeout=SCAN_TIMEOUT, return_adv=True)
    target = None
    for addr, (dev, adv) in found.items():
        is_watch = (addr.upper() == MAC.upper()) if MAC else (adv.local_name == NAME)
        mark = "  <== MONTRE" if is_watch else ""
        log(f"  {addr}  rssi={adv.rssi:>4}  nom={adv.local_name!r}{mark}")
        if is_watch:
            target = dev
            log(f"    services annoncés : {adv.service_uuids}")
            for cid, data in adv.manufacturer_data.items():
                log(f"    manufacturer 0x{cid:04X} : {hexdump(data)}")
            for uuid, data in adv.service_data.items():
                log(f"    service_data {uuid} : {hexdump(data)}")
    if target is None:
        log("Montre introuvable. Chargeur débranché ? Appli du téléphone déconnectée ?")
    return target


def on_notify(char):
    def handler(_sender, data: bytearray):
        log(f"NOTIF {char.uuid} : {hexdump(bytes(data))}")
    return handler


async def connect_and_subscribe(client: BleakClient, read_all=True):
    """Liste le GATT, lit les caractéristiques lisibles, s'abonne aux notifs.
    Retourne la liste des caractéristiques sur lesquelles on peut écrire."""
    writables = []
    for service in client.services:
        log(f"SERVICE {service.uuid}  ({service.description})")
        for char in service.characteristics:
            props = ",".join(char.properties)
            log(f"  CHAR {char.uuid}  handle={char.handle}  [{props}]  ({char.description})")
            if read_all and "read" in char.properties:
                try:
                    val = await client.read_gatt_char(char)
                    log(f"    lu : {hexdump(bytes(val))}")
                except Exception as e:
                    log(f"    lecture impossible : {e}")
            if "notify" in char.properties or "indicate" in char.properties:
                try:
                    await client.start_notify(char, on_notify(char))
                    log("    abonné aux notifications")
                except Exception as e:
                    log(f"    abonnement impossible : {e}")
            if "write" in char.properties or "write-without-response" in char.properties:
                writables.append(char)
            for desc in char.descriptors:
                log(f"    DESC {desc.uuid} handle={desc.handle}")
    return writables


async def explore():
    dev = await find_watch()
    if dev is None:
        return
    async with BleakClient(dev) as client:
        log(f"Connecté : {client.is_connected}")
        await connect_and_subscribe(client)
        log("Écoute des notifications pendant 30 s (manipule la montre pour voir passer des données)...")
        await asyncio.sleep(30)


async def shell():
    dev = await find_watch()
    if dev is None:
        return
    async with BleakClient(dev) as client:
        writables = await connect_and_subscribe(client, read_all=False)
        if not writables:
            log("Aucune caractéristique inscriptible.")
            return
        print("\nCaractéristiques inscriptibles :")
        for i, c in enumerate(writables):
            print(f"  [{i}] {c.uuid}  [{','.join(c.properties)}]")
        current = writables[0]
        print("\nCommandes : 'use N' pour choisir la caractéristique, "
              "des octets hex (ex: 02 a0 01) pour écrire, 'q' pour quitter.")
        loop = asyncio.get_running_loop()
        while client.is_connected:
            line = (await loop.run_in_executor(None, input, f"{current.uuid[4:8]}> ")).strip()
            if line in ("q", "quit", "exit"):
                break
            if line.startswith("use "):
                current = writables[int(line.split()[1])]
                continue
            if not line:
                continue
            try:
                data = bytes.fromhex(line)
            except ValueError:
                print("Hex invalide.")
                continue
            response = "write" in current.properties
            log(f"ENVOI {current.uuid} : {hexdump(data)}")
            await client.write_gatt_char(current, data, response=response)
            await asyncio.sleep(0.5)  # laisse le temps aux notifs de revenir


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "scan"
    actions = {"scan": find_watch, "explore": explore, "shell": shell}
    if cmd not in actions:
        print(__doc__)
        return
    asyncio.run(actions[cmd]())


if __name__ == "__main__":
    main()
