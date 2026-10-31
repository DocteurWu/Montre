"""Connexion persistante à la montre, partagée par l'interface web et le serveur MCP.

Une seule connexion BLE à la fois : toutes les commandes passent par un verrou,
et la connexion est rouverte automatiquement si la montre décroche.
"""

import asyncio
import json
import subprocess
from datetime import datetime
from pathlib import Path

from ido import Watch, decode_event

BUTTONS_FILE = Path(__file__).with_name("boutons.json")
BUTTONS = {"music_play": "Lecture", "music_pause": "Pause",
           "music_prev": "Précédent", "music_next": "Suivant"}
# action par bouton : {"type": "rien"|"heure"|"batterie"|"message"|"commande", "valeur": "..."}
DEFAULT_ACTIONS = {
    "music_play": {"type": "heure", "valeur": ""},
    "music_pause": {"type": "batterie", "valeur": ""},
    "music_prev": {"type": "message", "valeur": "Bouton precedent"},
    "music_next": {"type": "message", "valeur": "Bouton suivant"},
}


class WatchService:
    def __init__(self, buttons=False):
        self.watch = None
        self.lock = asyncio.Lock()
        self.history = []  # (heure, action, résultat)
        self.events = []   # (heure, nom de l'événement)
        self.buttons = buttons  # True : capte les boutons et exécute les actions
        self.actions = self._load_actions()

    @property
    def connected(self):
        return bool(self.watch and self.watch.client and self.watch.client.is_connected)

    async def _ensure(self):
        if not self.connected:
            self.watch = await Watch().connect()
            if self.buttons:
                self.watch.listeners.append(self._on_frame)
                await self.watch.music_menu(True)  # active les 4 boutons de l'écran musique

    # ---------- boutons ----------
    def _load_actions(self):
        try:
            return {**DEFAULT_ACTIONS, **json.loads(BUTTONS_FILE.read_text(encoding="utf-8"))}
        except (OSError, ValueError):
            return dict(DEFAULT_ACTIONS)

    def set_actions(self, actions):
        for k, a in actions.items():
            if k in BUTTONS and a.get("type") in ("rien", "heure", "batterie", "message", "commande"):
                self.actions[k] = {"type": a["type"], "valeur": str(a.get("valeur", ""))[:300]}
        BUTTONS_FILE.write_text(json.dumps(self.actions, ensure_ascii=False, indent=2), encoding="utf-8")
        return self.actions

    def _on_frame(self, data):
        evt = decode_event(data)
        if not evt:
            return
        self.events.insert(0, (datetime.now().strftime("%H:%M:%S"), evt))
        del self.events[100:]
        if evt in self.actions:
            asyncio.get_running_loop().create_task(self._do_action(evt))

    async def _do_action(self, evt):
        a = self.actions[evt]
        label = BUTTONS.get(evt, evt)
        try:
            if a["type"] == "heure":
                await self.message(label, datetime.now().strftime("Il est %H:%M:%S"))
            elif a["type"] == "batterie":
                s = await self.status()
                await self.message(label, f"Batterie {s['battery']} %")
            elif a["type"] == "message":
                await self.message(label, a["valeur"])
            elif a["type"] == "commande" and a["valeur"]:
                out = await asyncio.to_thread(subprocess.run, a["valeur"], shell=True,
                                              capture_output=True, text=True, timeout=30)
                await self.message(label, (out.stdout or out.stderr or "ok").strip()[:150])
        except Exception as e:
            self._log(f"bouton {label}", f"erreur : {e}")

    async def run(self, label, fn):
        """Exécute fn(watch) sous verrou ; réessaie une fois après reconnexion."""
        async with self.lock:
            for attempt in (1, 2):
                try:
                    await self._ensure()
                    result = await fn(self.watch)
                    self._log(label, "ok")
                    if isinstance(result, (bytes, bytearray)):
                        result = result.hex(" ")  # accusé de réception brut
                    return result
                except Exception as e:
                    self.watch = None
                    if attempt == 2:
                        self._log(label, f"erreur : {e}")
                        raise

    def _log(self, label, result):
        self.history.insert(0, (datetime.now().strftime("%H:%M:%S"), label, result))
        del self.history[50:]

    async def close(self):
        if self.connected:
            await self.watch.disconnect()

    # ---------- actions ----------
    async def message(self, title, text):
        return await self.run(f"message « {title} »", lambda w: w.message(title, text))

    async def call(self, name, number=""):
        return await self.run(f"appel « {name} »", lambda w: w.call(name, number))

    async def end_call(self):
        return await self.run("fin d'appel", lambda w: w.call_end())

    async def sync_time(self):
        return await self.run("mise à l'heure", lambda w: w.set_time())

    async def status(self):
        async def fn(w):
            info = await w.device_info()
            t = await w.get_time()
            return dict(battery=info["battery_level"], firmware=info["firmware"],
                        time=t.strftime("%Y-%m-%d %H:%M:%S"))
        return await self.run("état", fn)

    async def setting(self, name, on):
        actions = {
            "rappel_assis": lambda w: w.long_sit_reminder(on),
            "anti_perte": lambda w: w.anti_lost(on),
            "meteo": lambda w: w.weather(on),
            "ne_pas_deranger": lambda w: w.do_not_disturb(on),
            "lever_poignet": lambda w: w.raise_to_wake(on),
            "paysage": lambda w: w.landscape(on),
            "cardio_auto": lambda w: w.heart_rate_mode(0x88 if on else 0x55),
        }
        if name not in actions:
            raise ValueError(f"réglage inconnu : {name} (possibles : {', '.join(actions)})")
        return await self.run(f"{name} = {'on' if on else 'off'}", actions[name])

    SETTINGS = ["rappel_assis", "anti_perte", "meteo", "ne_pas_deranger",
                "lever_poignet", "paysage", "cardio_auto"]
