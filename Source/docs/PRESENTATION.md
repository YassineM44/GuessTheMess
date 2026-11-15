# Guess The Mess — short presentation outline

Copy these five sections into your team's preferred slide tool. Technical content is intentionally brief; demonstrate the real game alongside it.

## Slide 1 — Competitive multiplayer drawing game

- 2–5 players; host participates through a browser.
- One theme and N unique words for N players.
- Randomized order; each player draws once for 80 seconds.
- Correct-guess placement and drawer bonuses determine the final ranking.

Say: "Our focus is real network communication between independent clients and a central server."

## Slide 2 — One Python server, multiple browser clients

- Python: aiohttp for HTTP/WebSocket; aiortc for WebRTC.
- HTML/CSS/JavaScript browser clients; no player installation.
- Every browser connects directly to the server for both channels.
- Server controls words, timer, hints, permissions, scores, and session status.

Show: server console plus browsers on separate computers. Explain that running a host browser does not replace the other three required client computers.

## Slide 3 — TCP: reliable control and fair guesses

- WebSocket over TCP: room registration, chat, guesses, start/end, hints, scores.
- Server processes guesses before broadcasting anything.
- Correct answers are hidden; success messages reveal only player/placement/points.
- Server acceptance order decides first/second/etc.; clients never assign points.

Say: "A missing chat guess could change the winner, so reliable delivery matters here."

## Slide 4 — UDP: immediate ink, reliable recovery

- WebRTC data channel uses SCTP/DTLS over UDP, not raw UDP.
- Unordered previews, zero retransmissions; old ink does not hold up newer ink.
- Complete strokes are committed through TCP, repairing lost previews.
- Turn IDs, stroke IDs, sequence numbers, and revisions handle old or duplicate updates.
- Bucket/clear travel reliably because their ordering changes the canvas.

Show: live drawing and Network details with UDP receive/relay counters increasing.

## Slide 5 — Concurrency, disconnects, and bonus

- asyncio handles simultaneous connections; a lock serializes authoritative changes.
- WebSocket heartbeat detects loss; detected loss freezes the game timer/actions.
- Same-tab reconnect restores identity; the host can instead continue without the player.
- Host-player control can transfer; the server process itself does not migrate.
- Bonus: put a player on another network and reach the same server through Tailscale.

Say: "Tailscale provides reachability across networks. Our own WebRTC drawing remains the meaningful UDP traffic."

## Live-demo sequence

1. Launch the server on computer 1; open three clients on computers 2–4. Optional fourth player on computer 1.
2. Register nicknames, create/join a named room, show a leave/rejoin before starting.
3. Start with green UDP indicators, draw, send a wrong guess and a correct guess.
4. Show that the correct text is hidden and successful guessers cannot keep chatting.
5. Show a hint when 60 seconds remain, then rotation without a repeated drawer.
6. Demonstrate disconnect freeze and reconnect or Continue without them.
7. Finish the game and show the top ranks; start a rematch if time permits.
8. For the bonus, switch a client to a different internet connection, open the Tailscale address, and show drawing plus guessing.

## Assignment interpretation to explain accurately

Nickname registration is temporary session registration, not password-based authentication. Communication uses browser WebSocket/WebRTC APIs backed by real network connections, not manually implemented raw TCP/UDP sockets. Do not claim otherwise. Confirm these interpretations if your instructor gives stricter guidance than the supplied requirement sheet.
