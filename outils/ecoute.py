"""Écoute tout ce que la montre envoie d'elle-même (boutons, gestes, capteurs).

Usage : python ecoute.py [secondes] [camera|musique|appel]
Chaque trame reçue est affichée et notée dans montre_log.txt.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # accès à ido.py
import asyncio
import sys

from ido import Watch, decode_event
from montre_ble import hexdump, log


async def main():
    duree = int(sys.argv[1]) if len(sys.argv) > 1 else 90
    mode = sys.argv[2] if len(sys.argv) > 2 else ""

    async with Watch() as w:
        def on_frame(data):
            evt = decode_event(data)
            log(f"MONTRE -> {hexdump(data)}" + (f"   = {evt}" if evt else ""))
        w.listeners.append(on_frame)

        if mode != "appel":
            await w.message("PC", f"Ecoute {duree}s : appuie, glisse, secoue !")
            await asyncio.sleep(3)
        if mode == "camera":
            log(f"mode appareil photo : {await w.camera_mode(True)}")
        elif mode == "musique":
            log(f"mode musique : {await w.music_menu(True)}")
        elif mode == "appel":
            log(f"faux appel : {await w.call('Oui ou non ?', '0600000000')}")
        log(f"Écoute pendant {duree} s...")
        await asyncio.sleep(duree)
        if mode == "camera":
            await w.camera_mode(False)


if __name__ == "__main__":
    asyncio.run(main())
