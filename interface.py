"""Interface web locale pour piloter la montre : http://127.0.0.1:8765

Lance : python interface.py
L'interface garde la connexion Bluetooth ; le serveur MCP passe par elle quand elle tourne.
"""

import asyncio
import unicodedata
import webbrowser
from pathlib import Path

from aiohttp import web

from service import BUTTONS, WatchService

HOST, PORT = "127.0.0.1", 8765
PAGE = Path(__file__).with_name("interface.html")
ALLOWED_ORIGINS = {f"http://{HOST}:{PORT}", f"http://localhost:{PORT}"}
svc = WatchService(buttons=True)


@web.middleware
async def same_origin_only(request, handler):
    """Refuse les requêtes envoyées par d'autres sites (un bouton peut lancer une commande)."""
    origin = request.headers.get("Origin")
    if request.method != "GET" and origin and origin not in ALLOWED_ORIGINS:
        return web.json_response({"ok": False, "error": "origine refusée"}, status=403)
    return await handler(request)


async def keep_connected(_app):
    """Garde la montre connectée pour recevoir les appuis de boutons."""
    async def loop():
        while True:
            if not svc.connected:
                try:
                    async with svc.lock:
                        await svc._ensure()
                    svc._log("connexion (boutons actifs)", "ok")
                except Exception:
                    pass
            await asyncio.sleep(10)
    task = asyncio.create_task(loop())
    yield
    task.cancel()


def plain(text):
    """Retire les accents (l'écran de la montre ne les affiche pas forcément)."""
    return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()


async def handle(request, coro_factory):
    try:
        data = await request.json() if request.can_read_body else {}
        result = await coro_factory(data)
        return web.json_response({"ok": True, "result": result})
    except Exception as e:
        return web.json_response({"ok": False, "error": str(e)}, status=500)


def text_args(d):
    title, text = d.get("title", ""), d.get("text", "")
    if d.get("plain", True):
        title, text = plain(title), plain(text)
    return title, text


routes = web.RouteTableDef()


@routes.get("/")
async def index(_):
    return web.FileResponse(PAGE)


@routes.post("/api/message")
async def api_message(r):
    return await handle(r, lambda d: svc.message(*text_args(d)))


@routes.post("/api/call")
async def api_call(r):
    return await handle(r, lambda d: svc.call(plain(d.get("name", "")), d.get("number", "")))


@routes.post("/api/end_call")
async def api_end_call(r):
    return await handle(r, lambda d: svc.end_call())


@routes.post("/api/time")
async def api_time(r):
    return await handle(r, lambda d: svc.sync_time())


@routes.post("/api/setting")
async def api_setting(r):
    return await handle(r, lambda d: svc.setting(d["name"], bool(d["on"])))


@routes.get("/api/status")
async def api_status(r):
    return await handle(r, lambda d: svc.status())


@routes.get("/api/history")
async def api_history(_):
    return web.json_response({"connected": svc.connected, "history": svc.history,
                              "settings": svc.SETTINGS, "events": svc.events[:30]})


@routes.get("/api/buttons")
async def api_buttons_get(_):
    return web.json_response({"ok": True, "result": {"names": BUTTONS, "actions": svc.actions}})


@routes.post("/api/buttons")
async def api_buttons_set(r):
    return await handle(r, lambda d: _sync(svc.set_actions(d)))


@routes.post("/api/buttons_mode")
async def api_buttons_mode(r):
    return await handle(r, lambda d: svc.run("écran musique (boutons)", lambda w: w.music_menu(True)))


async def _sync(value):
    return value


async def on_shutdown(_):
    await svc.close()


def main():
    app = web.Application(middlewares=[same_origin_only])
    app.add_routes(routes)
    app.cleanup_ctx.append(keep_connected)
    app.on_shutdown.append(on_shutdown)
    print(f"Interface : http://{HOST}:{PORT}  (Ctrl+C pour arrêter)")
    if "--no-browser" not in __import__("sys").argv:
        webbrowser.open(f"http://{HOST}:{PORT}")
    web.run_app(app, host=HOST, port=PORT, print=None)


if __name__ == "__main__":
    main()
