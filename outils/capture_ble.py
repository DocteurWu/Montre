"""Décode les échanges Bluetooth entre l'appli officielle (VeryFit) et la montre.

1. Sur le téléphone : Options pour les développeurs > « Activer le journal HCI Bluetooth »,
   puis désactive et réactive le Bluetooth.
2. Utilise l'appli officielle avec la montre (chaque action que tu veux comprendre).
3. Sur le PC :
       python capture_ble.py              # récupère le journal via adb (bugreport, ~2 min)
       python capture_ble.py fichier.log  # ou analyse un btsnoop_hci.log déjà récupéré

Affiche chaque trame écrite vers la montre (APPLI ->) et chaque notification reçue
(<- MONTRE), avec le nom de la commande IDO quand il est connu.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # accès à ido.py
import struct
import subprocess
import sys
import zipfile
from datetime import datetime
from pathlib import Path

CMDS = {0x01: "OTA", 0x02: "GET", 0x03: "SET", 0x04: "BIND", 0x05: "MSG", 0x06: "APP_CTRL",
        0x07: "EVENT", 0x08: "HEALTH", 0x09: "HEALTH2", 0x0A: "WEATHER", 0x33: "V3", 0xAA: "TEST",
        0xF0: "RESET"}
ATT_OPS = {0x12: "write", 0x52: "write-cmd", 0x1B: "notif", 0x1D: "indic", 0x0B: "read-rsp"}
BTSNOOP_UNIX_OFFSET = 0x00DCDDB30F2F8000  # µs entre l'an 0 (référence btsnoop) et 1970


def recuperer_journal(dest=Path("btsnoop_hci.log")):
    zip_path = Path("bugreport.zip")
    print("Génération du bugreport via adb (1 à 3 minutes)...")
    subprocess.run(["adb", "bugreport", str(zip_path)], check=True)
    with zipfile.ZipFile(zip_path) as z:
        logs = [n for n in z.namelist() if n.endswith("btsnoop_hci.log")]
        if not logs:
            sys.exit("Pas de btsnoop_hci.log : active le journal HCI Bluetooth puis recommence.")
        dest.write_bytes(z.read(logs[-1]))
    print(f"Journal extrait : {dest}")
    return dest


def lire_btsnoop(path):
    """Génère (horodatage, reçu?, paquet HCI) pour chaque enregistrement."""
    data = Path(path).read_bytes()
    if data[:8] != b"btsnoop\x00":
        sys.exit("Ce n'est pas un fichier btsnoop.")
    off = 16
    while off + 24 <= len(data):
        _orig, incl, flags, _drops, ts = struct.unpack_from(">IIIIq", data, off)
        off += 24
        yield ts, bool(flags & 1), data[off:off + incl]
        off += incl


def trames_att(path):
    """Extrait les opérations ATT (écritures et notifications) des paquets ACL."""
    for ts, recu, pkt in lire_btsnoop(path):
        if not pkt or pkt[0] != 0x02 or len(pkt) < 12:  # H4 : 0x02 = ACL
            continue
        l2cap_cid = struct.unpack_from("<H", pkt, 7)[0]
        if l2cap_cid != 0x0004:  # canal ATT
            continue
        op = pkt[9]
        if op not in ATT_OPS or len(pkt) < 12:
            continue
        handle = struct.unpack_from("<H", pkt, 10)[0]
        yield ts, recu, ATT_OPS[op], handle, pkt[12:]


def decrire(valeur):
    if not valeur:
        return ""
    nom = CMDS.get(valeur[0])
    return f"{nom} {valeur[1]:02x}" if nom and len(valeur) > 1 else ""


def main():
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else recuperer_journal()
    n = 0
    for ts, recu, op, handle, val in trames_att(path):
        sens = "<- MONTRE" if recu else "APPLI ->"
        t = datetime.fromtimestamp((ts - BTSNOOP_UNIX_OFFSET) / 1e6).strftime("%H:%M:%S.%f")[:-3]
        print(f"{t} {sens:9} {op:9} h=0x{handle:04x}  {val.hex(' '):60}  {decrire(val)}")
        n += 1
    print(f"\n{n} trames ATT.")


if __name__ == "__main__":
    main()
