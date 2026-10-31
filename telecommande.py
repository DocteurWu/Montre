"""La montre comme télécommande : chaque bouton déclenche TA fonction Python.

Modifie le dictionnaire ACTIONS en bas du fichier, puis :
    python telecommande.py            # écran musique : 4 boutons (play, pause, préc., suiv.)
    python telecommande.py camera     # écran photo : 1 gros bouton
Ctrl+C pour quitter.
"""

import asyncio
import subprocess
import sys
from datetime import datetime

from ido import Watch, decode_event


def log(msg):
    print(f"[{datetime.now():%H:%M:%S}] {msg}")


async def run(actions, mode="musique"):
    queue = asyncio.Queue()
    loop = asyncio.get_running_loop()

    async with Watch() as w:
        def on_frame(data):
            evt = decode_event(data)
            if evt:
                loop.call_soon_threadsafe(queue.put_nowait, evt)
        w.listeners.append(on_frame)

        await w.set_time()
        if mode == "camera":
            await w.camera_mode(True)
        else:
            await w.music_menu(True)
        await w.message("PC", "Telecommande prete")
        log(f"Télécommande active (mode {mode}). Ctrl+C pour quitter.")

        while True:
            evt = await queue.get()
            action = actions.get(evt)
            log(f"événement : {evt}" + ("" if action else " (aucune action)"))
            if action:
                try:
                    result = action(w)
                    if asyncio.iscoroutine(result):
                        await result
                except Exception as e:
                    log(f"  erreur dans l'action : {e}")


# ------------------------------------------------------------------
# Tes actions : une fonction (w) -> ... par événement. w est la montre,
# tu peux donc aussi lui répondre (w.message, w.vibrate...).
# ------------------------------------------------------------------

async def heure(w):
    await w.message("Heure PC", datetime.now().strftime("%H:%M:%S"))


async def batterie(w):
    b = await w.battery()
    await w.message("Batterie", f"{b['level']}% - {b['voltage_mv']} mV")


def capture_ecran(w):
    subprocess.Popen(["snippingtool"])


ACTIONS = {
    "music_play": heure,
    "music_pause": heure,
    "music_next": batterie,
    "music_prev": capture_ecran,
    "photo": heure,
    "volume_up": lambda w: log("volume +"),
    "volume_down": lambda w: log("volume -"),
    "find_phone": lambda w: w.message("PC", "Je suis la !"),
}

if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "musique"
    try:
        asyncio.run(run(ACTIONS, mode))
    except KeyboardInterrupt:
        pass
