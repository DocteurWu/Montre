"""Serveur MCP « montre » : permet à Claude (ou tout client MCP) de piloter la montre.

Si l'interface web tourne (python interface.py), les commandes passent par elle,
car une seule connexion Bluetooth est possible. Sinon le serveur se connecte lui-même.
"""

import json
import unicodedata
import urllib.request

from mcp.server.fastmcp import FastMCP

from service import WatchService

API = "http://127.0.0.1:8765/api"
mcp = FastMCP("montre")
_direct = WatchService()


def _plain(text):
    return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()


def _via_interface(path, body=None):
    """Appelle l'interface web ; renvoie None si elle ne tourne pas."""
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(f"{API}/{path}", data=data,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            j = json.load(r)
    except urllib.error.HTTPError as e:
        j = json.load(e)
    except OSError:
        return None
    if not j.get("ok"):
        raise RuntimeError(j.get("error"))
    return j.get("result")


async def _do(path, body, direct):
    r = _via_interface(path, body)
    if r is None:
        r = await direct()
    return r


@mcp.tool()
async def envoyer_message(texte: str, titre: str = "Claude") -> str:
    """Affiche une notification sur la montre. Titre ≤ 30 caractères, texte ≤ 150.
    Les accents sont retirés (l'écran ne les affiche pas toujours)."""
    t, x = _plain(titre), _plain(texte)
    await _do("message", {"title": t, "text": x, "plain": True}, lambda: _direct.message(t, x))
    return f"Message affiché : {t} / {x}"


@mcp.tool()
async def faux_appel(nom: str, numero: str = "") -> str:
    """Affiche un appel entrant sur la montre (le bouton droit le rejette)."""
    n = _plain(nom)
    await _do("call", {"name": n, "number": numero}, lambda: _direct.call(n, numero))
    return f"Appel affiché : {n}"


@mcp.tool()
async def raccrocher() -> str:
    """Retire l'appel affiché sur la montre."""
    await _do("end_call", {}, _direct.end_call)
    return "Appel terminé"


@mcp.tool()
async def etat_montre() -> dict:
    """Batterie (%), version du firmware et heure de la montre."""
    return await _do("status", None, _direct.status)


@mcp.tool()
async def mettre_a_l_heure() -> str:
    """Règle l'heure de la montre sur celle du PC."""
    await _do("time", {}, _direct.sync_time)
    return "Heure réglée"


@mcp.tool()
async def regler(reglage: str, actif: bool) -> str:
    """Active/désactive une fonction. reglage parmi : rappel_assis, anti_perte, meteo,
    ne_pas_deranger, lever_poignet, paysage, cardio_auto."""
    await _do("setting", {"name": reglage, "on": actif}, lambda: _direct.setting(reglage, actif))
    return f"{reglage} = {'on' if actif else 'off'}"


@mcp.tool()
async def derniers_boutons(nombre: int = 10) -> list:
    """Derniers appuis sur les boutons de l'écran Musique de la montre : music_play,
    music_pause, music_prev, music_next. Nécessite l'interface web lancée (elle écoute la montre)."""
    try:
        with urllib.request.urlopen(f"{API}/history", timeout=5) as r:
            events = json.load(r).get("events", [])
    except OSError:
        raise RuntimeError("Lance d'abord l'interface : python interface.py")
    return [{"heure": t, "bouton": e} for t, e in events[:nombre]]


@mcp.tool()
async def configurer_bouton(bouton: str, action: str, valeur: str = "") -> dict:
    """Choisit ce que fait un bouton de la montre.
    bouton : music_play | music_pause | music_prev | music_next
    action : rien | heure | batterie | message (valeur = texte) | commande (valeur = commande PC)."""
    r = _via_interface("buttons", {bouton: {"type": action, "valeur": valeur}})
    if r is None:
        raise RuntimeError("Lance d'abord l'interface : python interface.py")
    return r[bouton]


if __name__ == "__main__":
    mcp.run()
