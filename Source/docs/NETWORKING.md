# Networking and classroom checklist

## Architecture

```text
Browser A (host also plays) ─┐
Browser B ──────────────────┼── Python server on host PC
Browser C ──────────────────┤      ├─ aiohttp: HTTP + WebSocket / TCP 8000
Optional browsers D/E ──────┘      └─ aiortc: WebRTC data channels / UDP dynamic ports
```

Every browser has its own WebSocket and its own WebRTC connection **to the server**. The server relays drawing to the other browsers. This is not a browser mesh. No STUN/TURN service, camera, or microphone is used. Host ICE candidates are gathered from local interfaces, including an available Tailscale interface. A reachable LAN or private overlay is assumed.

## Why two transports?

| Traffic | Transport | Reason |
|---|---|---|
| Session nicknames, create/join/leave, start/end | WebSocket over TCP | Ordered, reliable control messages |
| Chat, guesses, hints, scores, pause/resume | WebSocket over TCP | Losing or duplicating a guess must not change scoring |
| WebRTC offer/answer | WebSocket over TCP | Reliable connection negotiation |
| Live brush/eraser previews | WebRTC data channel, SCTP/DTLS over UDP | Unordered delivery and zero retransmissions avoid waiting for stale ink |
| Completed strokes, bucket fill, clear, recovery log | WebSocket over TCP | Everyone must eventually have the same canvas |

The drawing channel is explicitly configured with `ordered: false` and `maxRetransmits: 0`. It is not raw UDP: WebRTC supplies ICE, encryption, SCTP framing, and transport behavior. Losing a preview can briefly leave a gap; finishing the stroke reliably sends all its points to repair it. Bucket/clear operations are reliable because applying them in the wrong order would alter the picture.

Each update contains a turn ID; strokes also have an ID and preview sequence numbers. The server rejects drawing from non-drawers, obsolete turns, paused games, or invalid coordinates. Reliable commits carry ordered revision numbers. Clients ignore late previews for committed strokes and can request a full operation log on reconnect or revision gaps.

There is no automatic TCP replacement for UDP preview traffic. **Network details** shows actual UDP receive/relay counts and reliable commit counts for the demo. These are aggregate counters since server startup.

## Simultaneous players and authority

An asyncio event loop handles socket I/O and the turn ticker concurrently. Room mutations are serialized under an asyncio lock; the server's acceptance order determines guess placement. A monotonic clock drives the timer. Clients display server time; they cannot award themselves points, choose a secret word, reveal hints early, or draw during someone else's turn.

The answer is sent only to the drawer. Guess text is checked before publishing chat. Correct guesses and close guesses are replaced with public success announcements or private feedback respectively.

Heartbeat WebSockets detect closed/unresponsive connections. Detection of a physical outage is not instantaneous; the game freezes when the server detects it. Reconnect tokens restore active sessions without passwords. Tokens are bearer credentials kept in the browser tab's session storage, not in room invite links.

## Main LAN demonstration

1. Use the assignment's **four separate computers**: the server on one, a browser client on each of the other three. The server computer can also open a browser client, giving four players.
2. Use the same Wi-Fi/hotspot/LAN. Confirm that peer-device access is allowed.
3. Launch `GuessTheMess.exe` on the host.
4. Share the **Wi-Fi or Ethernet** address printed in the console, not `localhost`, `127.0.0.1`, a Docker/virtual-machine address, or an unrelated VPN address.
5. Open the host form, select Wi-Fi / LAN and a theme, then create the room. Copy Invite shows the selected host network address. Players open it and join with nicknames.
6. Confirm each player's green UDP status. Start and demonstrate drawing, public wrong guesses, hidden correct guesses, hints, turn rotation, and final scores.
7. Temporarily interrupt a player's connection or refresh their tab to demonstrate freeze and return. For Continue without them, disconnect a non-host player and use the host's controls.

LAN-only play works without external internet once packages are installed. No assets load from a CDN.

## Firewall and network troubleshooting

- **Page will not open:** first open the printed address on the host itself. Check that the server console is still open, the address/port is correct, and devices can reach each other. Guest Wi-Fi commonly isolates clients. Try an approved hotspot/router.
- **Page opens but UDP is not ready:** allow the host's `GuessTheMess.exe` (or `.venv/Scripts/python.exe` for source mode) inbound UDP on the chosen trusted network profile. WebRTC uses dynamically allocated UDP ports, so a TCP-only port 8000 exception is insufficient. Also check client browser/firewall policies, then use Repair UDP or refresh.
- **Windows firewall prompt:** permit the actual server executable on the approved profile. Do not disable the entire firewall. Institution-managed firewall changes may require IT assistance.
- **Invite copying:** the room stores the selected server address, so Copy Invite works even when the host opened localhost. Refresh the host form if interfaces change before creation. If the chosen address changes afterward, create a new room. A manual-copy prompt is provided if clipboard copying is unavailable.
- **Port in use:** stop the older server or launch with `--port 8080`, then share the new port.
- **Cannot reconnect:** use the same tab. If the server restarted or the host continued without that player, the old session is no longer valid; join a waiting/finished room again.
- **Browser issues:** use current Edge, Chrome, or Firefox with JavaScript/WebRTC enabled. This game does not request capture permissions. Managed browser policies can disable WebRTC.

The app uses plain HTTP/WebSocket on the local/private network; WebRTC drawing is DTLS-encrypted. This is a classroom/LAN project, not a hardened public hosting service. Do not publish port 8000 to the public internet as part of the default setup.

## Bonus: different networks with Tailscale

The room connection mode is chosen at creation and stays fixed through rematches. It chooses the advertised join address; it does not block the server's other interfaces or migrate existing connections.

Tailscale provides private reachability, not game logic. It does not move someone onto your Wi-Fi.

1. Install Tailscale on the host and participating Windows computers.
2. Sign in and grant those devices access to the same tailnet (private Tailscale network), or use appropriate device-sharing permissions. Do not share passwords.
3. Keep the host on one Wi-Fi. Put another player on a **different** Wi-Fi or phone hotspot. Both need working internet for Tailscale.
4. Confirm the private Tailscale connection and access policy allow the player to reach the host's TCP game port and WebRTC UDP traffic. Tailscale access rules must allow more than only TCP 8000.
5. Start the same game server and select **Tailscale** before creating the room. The form checks the host's connection and enables creation only when ready. Use the room's Copy Invite button to share its Tailscale address.
6. Confirm green TCP and UDP statuses and draw. Check Network details for increasing UDP counters. Demonstrate actual guesses/scores across the two networks.

Tailscale may use a direct encrypted route or its relay infrastructure, depending on network conditions. Either can provide cross-network communication. We do not count Tailscale's tunnel traffic as our game's UDP implementation; the game itself uses a WebRTC UDP data channel. No Tailscale Funnel or public hosting is needed for this private demo.

**Must still be checked on the actual devices:** the destination PC, faculty Wi-Fi, Windows firewall profiles, Tailscale access policies, and full gameplay across two networks. These depend on the actual network configuration.

## Primary references

- aiohttp server/WebSocket API: https://docs.aiohttp.org/en/stable/web_reference.html
- aiortc connection/data-channel API: https://aiortc.readthedocs.io/en/stable/api.html
- WebRTC data channels: https://www.rfc-editor.org/rfc/rfc8831.html
- TCP: https://www.rfc-editor.org/rfc/rfc9293.html
- UDP usage guidance: https://www.rfc-editor.org/rfc/rfc8085.html
- Tailscale private service sharing: https://tailscale.com/docs/share-web-server
