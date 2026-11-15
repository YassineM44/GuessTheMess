"""Guess The Mess: a LAN-first WebSocket + WebRTC drawing server."""
import argparse
import asyncio
import contextlib
import ipaddress
import json
import logging
import math
import os
import secrets
import shutil
import subprocess
import time
import webbrowser
from pathlib import Path

import ifaddr
from aiohttp import web, WSMsgType
from aiortc import RTCConfiguration, RTCPeerConnection, RTCSessionDescription

from game import Room

ROOT = Path(__file__).resolve().parent
WORDS = json.loads((ROOT / "words.json").read_text(encoding="utf-8"))
COLORS = {"#242636", "#ef5261", "#ffab40", "#f7d34c", "#4dbb87", "#4989ed", "#9567df", "#ffffff"}
log = logging.getLogger("sketch")
TAILSCALE_RANGE = ipaddress.ip_network("100.64.0.0/10")


def network_options():
    """Read current interfaces / Tailscale status. No settings or addresses are saved."""
    lan = []
    for adapter in ifaddr.get_adapters():
        if any(word in adapter.nice_name.casefold() for word in ("vethernet", "vmware", "virtualbox", "loopback")):
            continue
        for address in adapter.ips:
            if not isinstance(address.ip, str):
                continue
            ip = ipaddress.ip_address(address.ip)
            if ip.is_loopback or ip.is_link_local or ip.is_unspecified or ip in TAILSCALE_RANGE:
                continue
            if not any(item["ip"] == str(ip) for item in lan):
                lan.append({"ip": str(ip), "label": adapter.nice_name})
    result = {"lan": {"ready": bool(lan), "addresses": lan,
                      "message": "Share with players on the same network." if lan else "Connect the host PC to Wi-Fi or Ethernet, then refresh."},
              "tailscale": {"ready": False, "addresses": [], "message": "Tailscale is not installed on the host PC."}}
    executable = shutil.which("tailscale")
    if not executable and os.name == "nt":
        path = Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Tailscale" / "tailscale.exe"
        if path.is_file():
            executable = str(path)
    if not executable:
        return result
    ts = result["tailscale"]
    try:
        process = subprocess.run([executable, "status", "--json"], capture_output=True,
                                 text=True, timeout=3,
                                 creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        if process.returncode:
            ts["message"] = "Open Tailscale on the host PC and connect, then refresh."
            return result
        status = json.loads(process.stdout)
        backend = status.get("BackendState")
        if backend != "Running":
            ts["message"] = "Sign in to Tailscale on the host PC, then refresh." if backend in ("NeedsLogin", "NeedsMachineAuth") else "Connect Tailscale on the host PC, then refresh."
            return result
        for value in status.get("Self", {}).get("TailscaleIPs", []):
            ip = ipaddress.ip_address(value)
            if ip.version == 4 and ip in TAILSCALE_RANGE:
                ts["addresses"].append({"ip": str(ip), "label": "Tailscale"})
        ts["ready"] = bool(ts["addresses"])
        ts["message"] = "Host connected. Players must connect to the tailnet too." if ts["ready"] else "Tailscale has no IPv4 address yet. Refresh after it connects."
    except (OSError, subprocess.TimeoutExpired, ValueError, AttributeError, TypeError):
        ts["message"] = "Cannot read Tailscale status. Open Tailscale on the host PC, then refresh."
    return result


def drawing_op(raw, preview=False):
    """Validate and rebuild payloads; never forward arbitrary client objects."""
    if not isinstance(raw, dict):
        raise ValueError("Invalid drawing update.")
    op = {"id": str(raw.get("id", "")), "kind": raw.get("kind"),
          "color": raw.get("color", "#242636")}
    if not 1 <= len(op["id"]) <= 64 or op["color"] not in COLORS:
        raise ValueError("Invalid drawing style.")
    if op["kind"] == "stroke":
        points = raw.get("points")
        if not isinstance(points, list) or not 1 <= len(points) <= (24 if preview else 1500):
            raise ValueError("Invalid stroke length.")
        op["points"] = []
        for pt in points:
            if (not isinstance(pt, list) or len(pt) != 2 or
                    any(type(n) not in (int, float) or not math.isfinite(n) or not 0 <= n <= 1 for n in pt)):
                raise ValueError("Invalid drawing coordinates.")
            op["points"].append([round(pt[0], 5), round(pt[1], 5)])
        op["erase"] = raw.get("erase") is True
    elif op["kind"] == "fill" and not preview:
        pt = raw.get("point")
        if (not isinstance(pt, list) or len(pt) != 2 or
                any(type(n) not in (int, float) or not math.isfinite(n) or not 0 <= n <= 1 for n in pt)):
            raise ValueError("Invalid fill point.")
        op["point"] = pt
    elif op["kind"] == "clear" and not preview:
        pass
    else:
        raise ValueError("Invalid drawing tool.")
    if preview:
        seq = raw.get("seq")
        if type(seq) is not int or not 0 <= seq <= 100000:
            raise ValueError("Invalid drawing sequence.")
        op["seq"] = seq
    return op


class GameServer:
    def __init__(self):
        self.rooms = {}
        self.clients = {}  # (room code, player ID) -> websocket
        self.peers = {}
        self.channels = {}
        self.lock = asyncio.Lock()
        self.stats = {"tcp_messages": 0, "udp_received": 0, "udp_relayed": 0, "commits": 0}
        self.rate = {}

    async def send(self, ws, data):
        if not ws.closed:
            try:
                await asyncio.wait_for(ws.send_json(data), 2)
            except (ConnectionError, RuntimeError, asyncio.TimeoutError):
                await ws.close()

    async def flush(self, room, states=True):
        events, room.events = room.events, []
        targets = [(pid, self.clients.get((room.code, pid))) for pid in room.players]
        async def deliver(pid, ws):
            if ws is None or ws.closed:
                return
            for event in events:
                await self.send(ws, event)
            if states:
                await self.send(ws, room.state(pid))
        await asyncio.gather(*(deliver(pid, ws) for pid, ws in targets))

    async def close_peer(self, key):
        pc = self.peers.pop(key, None)
        self.channels.pop(key, None)
        if pc:
            await pc.close()

    async def negotiate(self, room, pid, ws, data):
        key = (room.code, pid)
        await self.close_peer(key)
        room.players[pid].rtc_ready = False
        pc = RTCPeerConnection(RTCConfiguration(iceServers=[]))
        self.peers[key] = pc

        @pc.on("datachannel")
        def channel_received(channel):
            if channel.label != "drawing":
                channel.close()
                return
            self.channels[key] = channel

            @channel.on("open")
            def opened():
                if self.peers.get(key) is pc:
                    room.players[pid].rtc_ready = True

            @channel.on("close")
            def closed():
                if self.peers.get(key) is pc:
                    room.players[pid].rtc_ready = False

            @channel.on("message")
            def message(payload):
                if self.peers.get(key) is not pc or self.clients.get(key) is not ws:
                    return
                # A small UDP hello proves the data channel is open on both ends.
                if payload == "hello":
                    room.players[pid].rtc_ready = True
                    channel.send("hello")
                    return
                if not isinstance(payload, str) or len(payload) > 8000:
                    return
                now = time.monotonic()
                window, count = self.rate.get(key, (now, 0))
                if now - window > 1:
                    window, count = now, 0
                self.rate[key] = (window, count + 1)
                if count > 90:
                    return
                try:
                    data = json.loads(payload)
                    if not room.can_draw(pid, data.get("turn")):
                        return
                    op = drawing_op(data.get("op"), preview=True)
                    if op["id"] in room.op_ids:
                        return
                    self.stats["udp_received"] += 1
                    packet = json.dumps({"type": "preview", "turn": room.turn_id, "op": op})
                    for other in room.members():
                        if other.id == pid:
                            continue
                        dest = self.channels.get((room.code, other.id))
                        if dest and dest.readyState == "open" and dest.bufferedAmount < 128000:
                            try:
                                dest.send(packet)
                                self.stats["udp_relayed"] += 1
                            except Exception:
                                log.debug("Data channel send failed", exc_info=True)
                except (ValueError, TypeError, AttributeError):
                    return

        try:
            sdp = data.get("sdp")
            if not isinstance(sdp, str) or len(sdp) > 100000:
                raise ValueError("Invalid WebRTC offer.")
            await pc.setRemoteDescription(RTCSessionDescription(sdp=sdp, type="offer"))
            await pc.setLocalDescription(await pc.createAnswer())
            await self.send(ws, {"type": "answer", "sdp": pc.localDescription.sdp})
        except Exception as exc:
            await self.close_peer(key)
            log.warning("WebRTC setup failed: %s", exc)
            raise ValueError("Drawing connection failed. Try Repair UDP, or check the firewall.") from exc

    async def websocket(self, request):
        # Reject browser connections from other origins; this server uses no cookies.
        origin = request.headers.get("Origin")
        if origin and origin not in (f"http://{request.host}", f"https://{request.host}"):
            raise web.HTTPForbidden(text="Open the game from this server's own address.")
        ws = web.WebSocketResponse(heartbeat=10, max_msg_size=160000)
        await ws.prepare(request)
        room = pid = None
        key = None
        try:
            async for msg in ws:
                if msg.type != WSMsgType.TEXT:
                    continue
                action = None
                try:
                    data = json.loads(msg.data)
                    if not isinstance(data, dict):
                        raise ValueError("Invalid request.")
                    action = data.get("type")
                    # Do slow interface/status checks outside the game-state lock.
                    options = await asyncio.to_thread(network_options) if action == "create" and room is None else None
                    self.stats["tcp_messages"] += 1
                    async with self.lock:
                        if room is None:
                            if action == "resume":
                                room = self.rooms.get(str(data.get("code", "")).upper())
                                if not room:
                                    raise ValueError("That room no longer exists. Join or create another.")
                                p = next((p for p in room.players.values()
                                          if secrets.compare_digest(p.token, str(data.get("token", "")))), None)
                                if p is None or not p.active:
                                    room = None
                                    raise ValueError("This session has ended. Join the room again.")
                                pid = p.id
                                previous = self.clients.get((room.code, pid))
                                if previous and not previous.closed:
                                    room = pid = None
                                    raise ValueError("This player is already connected in another window.")
                                room.reconnect(pid)
                            elif action in ("create", "join"):
                                if action == "create":
                                    theme = data.get("theme")
                                    name = str(data.get("room_name", "")).strip()
                                    if theme not in WORDS or not 1 <= len(name) <= 40:
                                        raise ValueError("Choose a theme and a room name of 1–40 characters.")
                                    if len(self.rooms) >= 100:
                                        raise ValueError("Server room limit reached. Ask the host to restart it.")
                                    connection_mode = data.get("connection_mode", "lan")
                                    if connection_mode not in ("lan", "tailscale"):
                                        raise ValueError("Choose Wi-Fi / LAN or Tailscale before creating the room.")
                                    selected = options[connection_mode]
                                    if not selected["ready"]:
                                        raise ValueError(selected["message"])
                                    valid_addresses = [item["ip"] for item in selected["addresses"]]
                                    address = data.get("invite_address") or valid_addresses[0]
                                    if address not in valid_addresses:
                                        raise ValueError("That address is no longer available. Refresh the connection options.")
                                    port = request.transport.get_extra_info("sockname")[1]
                                    code = secrets.token_hex(3).upper()
                                    while code in self.rooms:
                                        code = secrets.token_hex(3).upper()
                                    candidate = Room(code, name, theme, WORDS, connection_mode,
                                                     f"http://{address}:{port}")
                                else:
                                    candidate = self.rooms.get(str(data.get("code", "")).strip().upper())
                                    if not candidate:
                                        raise ValueError("Room not found. Check the six-character room code.")
                                p = candidate.add(str(data.get("name", "")), str(data.get("avatar", "👾")))
                                room, pid = candidate, p.id
                                self.rooms[room.code] = room
                            else:
                                raise ValueError("Join a room first.")
                            key = (room.code, pid)
                            self.clients[key] = ws
                            room.last_active = time.monotonic()
                            await self.send(ws, {"type": "welcome", "id": pid, "code": room.code,
                                                 "token": room.players[pid].token})
                            await self.send(ws, {"type": "canvas", "turn": room.turn_id, "ops": room.ops})
                            await self.flush(room)
                            continue
                        room.last_active = time.monotonic()
                        if action == "offer":
                            await self.negotiate(room, pid, ws, data)
                        elif action == "start":
                            room.start(pid)
                        elif action == "chat":
                            notice = room.guess(pid, str(data.get("text", "")))
                            if notice:
                                await self.send(ws, notice)
                        elif action == "continue":
                            room.continue_without(pid)
                        elif action == "wait":
                            if pid != room.host:
                                raise ValueError("Only the host can choose to wait.")
                            room.system("The host is waiting for disconnected players to return.")
                        elif action == "commit":
                            if not room.can_draw(pid, data.get("turn")):
                                raise ValueError("Drawing is not available right now.")
                            op = drawing_op(data.get("op"))
                            if op["id"] in room.op_ids:
                                continue
                            cost = len(op.get("points", [])) + 1
                            if len(room.ops) >= 3000 or room.points_used + cost > 100000:
                                raise ValueError("Canvas limit reached for this turn.")
                            op["rev"] = len(room.ops) + 1
                            room.ops.append(op)
                            room.op_ids.add(op["id"])
                            room.points_used += cost
                            self.stats["commits"] += 1
                            room.events.append({"type": "commit", "turn": room.turn_id, "op": op})
                        elif action == "sync":
                            await self.send(ws, {"type": "canvas", "turn": room.turn_id, "ops": room.ops})
                        elif action == "diagnostics":
                            await self.send(ws, {"type": "diagnostics", "stats": self.stats})
                        elif action == "leave":
                            room.disconnect(pid, voluntary=True)
                            if room.host == pid:
                                room.host = next((p.id for p in room.members() if p.connected), None)
                            self.clients.pop(key, None)
                            await self.flush(room)
                            await self.close_peer(key)
                            await self.send(ws, {"type": "left"})
                            room = pid = key = None
                            continue
                        else:
                            raise ValueError("Unknown request.")
                        await self.flush(room, states=action != "commit")
                except (ValueError, TypeError, KeyError) as exc:
                    await self.send(ws, {"type": "error", "text": str(exc), "reset": action == "resume"})
                except Exception:
                    log.exception("Request failed")
                    await self.send(ws, {"type": "error", "text": "That action failed. Please try again."})
        finally:
            if room and key and self.clients.get(key) is ws:
                async with self.lock:
                    self.clients.pop(key, None)
                    room.disconnect(pid)
                    await self.close_peer(key)
                    await self.flush(room)
        return ws

    async def ticker(self):
        last = time.monotonic()
        while True:
            await asyncio.sleep(.5)
            now = time.monotonic()
            dt, last = min(now - last, 2), now
            async with self.lock:
                for code, room in list(self.rooms.items()):
                    room.tick(dt)
                    await self.flush(room)
                    if not any(p.connected for p in room.members()) and now - room.last_active > 1800:
                        self.rooms.pop(code, None)

    async def lifecycle(self, app):
        task = asyncio.create_task(self.ticker())
        yield
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
        await asyncio.gather(*(ws.close(code=1001, message=b"Server stopping") for ws in self.clients.values()))
        await asyncio.gather(*(pc.close() for pc in list(self.peers.values())))

    def app(self):
        app = web.Application(client_max_size=160000)
        app.router.add_get("/ws", self.websocket)
        async def index(request):
            return web.FileResponse(ROOT / "web" / "index.html", headers={"Cache-Control": "no-cache"})
        async def health(request):
            return web.json_response({"status": "ok", "game": "Guess The Mess"})
        app.router.add_get("/", index)
        app.router.add_get("/health", health)
        async def networks(request):
            options = await asyncio.to_thread(network_options)
            local = request.transport.get_extra_info("sockname")[0]
            return web.json_response({**options, "current_address": local}, headers={"Cache-Control": "no-store"})
        app.router.add_get("/network-options", networks)
        app.router.add_static("/static/", ROOT / "web", show_index=False)
        app.cleanup_ctx.append(self.lifecycle)
        return app


def main():
    parser = argparse.ArgumentParser(description="Guess The Mess game server")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()
    logging.basicConfig(level=logging.WARNING)
    print("\n  GUESS THE MESS — draw, guess, repeat.\n", flush=True)
    print(f"  This computer: http://localhost:{args.port}")
    print("  Share ONE of these addresses with other players:")
    lan_addresses = []
    for adapter in ifaddr.get_adapters():
        for address in adapter.ips:
            if isinstance(address.ip, str):
                ip = ipaddress.ip_address(address.ip)
                if not ip.is_loopback and not ip.is_link_local:
                    label = "Tailscale / bonus" if ip in ipaddress.ip_network("100.64.0.0/10") else adapter.nice_name
                    print(f"    http://{ip}:{args.port}  ({label})")
                    if ip not in ipaddress.ip_network("100.64.0.0/10"):
                        lan_addresses.append(str(ip))
    print("\n  Same Wi-Fi: use the Wi-Fi address. Bonus: use the Tailscale address.")
    print("  Allow Python on your PRIVATE network if Windows Firewall asks.")
    print("  Keep this window open. Press Ctrl+C to stop.\n", flush=True)
    app = GameServer().app()
    if not args.no_browser:
        async def open_browser(app):
            await asyncio.sleep(.8)
            address = lan_addresses[0] if lan_addresses else "localhost"
            await asyncio.to_thread(webbrowser.open, f"http://{address}:{args.port}")
        async def on_start(app):
            app["browser_task"] = asyncio.create_task(open_browser(app))
        app.on_startup.append(on_start)
    try:
        web.run_app(app, host="0.0.0.0", port=args.port, access_log=None)
    except OSError as exc:
        print(f"Could not start: {exc}\nAnother server may already use port {args.port}.")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
