"""Pont téléphone -> montre : chaque nouvelle notification du téléphone (lue via adb)
s'affiche sur la montre.

Usage : python pont_telephone.py [--tout]
  Par défaut, les notifications système et permanentes sont ignorées.
  Modifie IGNORER / SEULEMENT ci-dessous pour choisir les applis.
Passe par l'interface web si elle tourne, sinon se connecte directement à la montre.
"""

import asyncio
import re
import subprocess
import sys
import unicodedata

from mcp_montre import _via_interface
from service import WatchService

INTERVALLE = 3  # secondes entre deux lectures
IGNORER = {"android", "com.android.systemui", "com.miui.securitycenter", "com.miui.notification",
           "com.android.providers.downloads", "com.google.android.gms"}
SEULEMENT = set()  # ex. {"com.whatsapp", "com.google.android.gm"} pour ne garder que celles-là

RECORD = re.compile(r"NotificationRecord\(0x\w+: pkg=(\S+) .*?key=(\S+): Notification\(.*?flags=(0x[0-9a-f]+)")
FIELD = re.compile(r"android\.(title|text|bigText)=(?:String|SpannableString) \((.*)")

FLAG_ONGOING, FLAG_FOREGROUND = 0x02, 0x40


def plain(text):
    return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()


def lire_notifications():
    """Retourne {clé: (appli, titre, texte, flags)} des notifications affichées."""
    out = subprocess.run(["adb", "shell", "dumpsys", "notification", "--noredact"],
                         capture_output=True, text=True, encoding="utf-8", errors="replace").stdout
    notifs, cur = {}, None
    for line in out.splitlines():
        m = RECORD.search(line)
        if m:
            pkg, key, flags = m.group(1), m.group(2), int(m.group(3), 16)
            cur = notifs.setdefault(key, {"pkg": pkg, "flags": flags})
            continue
        f = FIELD.search(line)
        if f and cur is not None and f.group(1) not in cur:
            cur[f.group(1)] = f.group(2).rstrip(")").strip()
    return notifs


def a_transferer(n, tout):
    if tout:
        return True
    if n["flags"] & (FLAG_ONGOING | FLAG_FOREGROUND):
        return False
    if SEULEMENT and n["pkg"] not in SEULEMENT:
        return False
    return n["pkg"] not in IGNORER and (n.get("title") or n.get("text"))


def nom_appli(pkg):
    return pkg.split(".")[-1].capitalize()[:12]


async def main():
    tout = "--tout" in sys.argv
    direct = WatchService()
    deja_vues = set(lire_notifications())  # on ne renvoie pas l'existant
    print(f"Pont actif ({len(deja_vues)} notifications déjà présentes ignorées). Ctrl+C pour arrêter.")
    while True:
        await asyncio.sleep(INTERVALLE)
        try:
            notifs = lire_notifications()
        except FileNotFoundError:
            sys.exit("adb introuvable dans le PATH")
        for key, n in notifs.items():
            if key in deja_vues:
                continue
            deja_vues.add(key)
            if not a_transferer(n, tout):
                continue
            titre = plain(n.get("title") or nom_appli(n["pkg"]))[:30]
            texte = plain(n.get("bigText") or n.get("text") or "")[:150]
            print(f"-> montre : [{nom_appli(n['pkg'])}] {titre}")
            try:
                if _via_interface("message", {"title": titre, "text": texte, "plain": True}) is None:
                    await direct.message(titre, texte)
            except Exception as e:
                print(f"   échec : {e}")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
