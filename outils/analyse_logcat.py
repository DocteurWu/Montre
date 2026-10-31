"""Extrait les trames montre <-> VeryFit Pro des journaux de l'appli (logcat).

VeryFit Pro écrit chaque trame en clair : « TX : 03 11 ... » et « RX : 03 11 ... ».
Usage : python analyse_logcat.py [veryfit_logcat.txt] [--resume]
  --resume : une ligne par commande distincte (cmd, clé) avec un exemple.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # accès à ido.py
import re
import sys
from collections import OrderedDict

from capture_ble import CMDS

LINE = re.compile(r"^(\d\d-\d\d \d\d:\d\d:\d\d\.\d+).*?\b(TX|RX)\s*:\s*((?:[0-9A-Fa-f]{2} ?)+)")
KNOWN = {
    (0x02, 0x01): "infos", (0x02, 0x02): "fonctions", (0x02, 0x03): "heure", (0x02, 0x04): "MAC",
    (0x02, 0x05): "batterie", (0x02, 0xA0): "live", (0x03, 0x01): "régler heure",
    (0x03, 0x02): "alarme", (0x03, 0x03): "objectif", (0x03, 0x10): "profil", (0x03, 0x11): "unités",
    (0x03, 0x20): "rappel assis", (0x03, 0x21): "anti-perte", (0x03, 0x22): "main",
    (0x03, 0x23): "OS", (0x03, 0x24): "seuils cardio", (0x03, 0x25): "mode cardio",
    (0x03, 0x28): "lever poignet", (0x03, 0x29): "ne pas déranger", (0x03, 0x2A): "musique",
    (0x03, 0x2B): "affichage", (0x03, 0x2D): "météo", (0x03, 0x2E): "sports", (0x03, 0x30): "notifs",
    (0x04, 0x01): "liaison", (0x04, 0x02): "déliaison", (0x05, 0x01): "appel", (0x05, 0x03): "message",
    (0x06, 0x01): "écran musique", (0x06, 0x02): "écran photo", (0x06, 0x04): "faire sonner",
    (0x07, 0x01): "ÉVÉNEMENT bouton", (0x07, 0x02): "trouver téléphone",
    (0x08, 0x01): "début sync", (0x08, 0x02): "fin sync", (0x0A, 0x01): "météo données",
}


def trames(path):
    with open(path, encoding="utf-8-sig", errors="replace") as f:
        for line in f:
            m = LINE.search(line)
            if m:
                yield m.group(1), m.group(2), bytes.fromhex(m.group(3))


def nom(b):
    if not b:
        return ""
    if b[0] == 0x33:
        return "V3 (protocole long)"
    k = (b[0], b[1]) if len(b) > 1 else (b[0], None)
    return KNOWN.get(k) or (f"{CMDS.get(b[0], '?')} {b[1]:02x}" if len(b) > 1 else "?")


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    path = args[0] if args else "veryfit_logcat.txt"
    if "--resume" in sys.argv:
        vus = OrderedDict()
        for t, sens, b in trames(path):
            key = (sens, b[:2] if b[:1] != b"\x33" else b[:1] + b[5:6] + b[9:11])
            vus.setdefault(key, (t, sens, b, 0))
            t0, s0, b0, n = vus[key]
            vus[key] = (t0, s0, b0, n + 1)
        for t, sens, b, n in vus.values():
            print(f"{t}  {'APPLI ->' if sens == 'TX' else '<- MONTRE'}  x{n:<3} {nom(b):22} {b.hex(' ')}")
        return
    for t, sens, b in trames(path):
        print(f"{t}  {'APPLI ->' if sens == 'TX' else '<- MONTRE'}  {nom(b):22} {b.hex(' ')}")


if __name__ == "__main__":
    main()
