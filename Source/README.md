# Guess The Mess: source code guide

The **Source** folder contains the readable project. The executable outside it is a packaged copy for playing. An IDE is optional. To run the Python source, use Python 3.12, 64-bit.

## Main code

| File | Responsibility |
|---|---|
| `server.py` | HTTP, WebSocket/TCP, WebRTC/UDP, sessions, rooms, action validation and relay. |
| `game.py` | Players, words, turns, guesses, points, hints, timer, disconnect decisions. |
| `web/app.js` | Browser connections, canvas tools, chat, rendering server state. |
| `web/experience.js` | Sounds, avatars, theme preferences, countdown feedback, confetti. |
| `web/index.html` | Page structure: lobby, canvas, chat, controls. |
| `web/style.css` | Base layout and responsive styles. |
| `web/personality.css` | Doodle styling, dark mode, player cards, animation. |
| `words.json` | Ten words each for Animals, Technology, and Food. |

Python runs on the server. HTML/CSS/JavaScript run in each browser. aiohttp and aiortc handle protocol internals; our code configures and uses them.

## A guess, end to end

1. `web/app.js` sends a guess over WebSocket/TCP.
2. `server.py` receives it in `websocket()` and calls `Room.guess()`.
3. `game.py` checks the answer before publishing chat. Correct guesses award points and hide the answer; close guesses produce private feedback.
4. `server.py` sends events and updated state to players.
5. `web/app.js` displays scores/chat; `web/experience.js` plays local feedback.

Live drawing uses an unordered WebRTC data channel over UDP. Completed strokes use reliable WebSocket/TCP commits to repair missing previews. Every browser connects to the central server for both transports.

## Supporting material

- **docs/**: networking/Tailscale explanation, presentation outline, third-party notices.
- **tools/build_portable.py**: creates the single Windows executable and transfer ZIPs. Not game logic.
- **requirements.txt**: main Python dependencies. **tools/requirements-lock.txt**: complete tested versions.
- **tools/Setup.bat** and **tools/Start Server.bat**: optional launchers for running source instead of the packaged executable.

## Run the source

Install Python 3.12 x64, then double-click `tools/Setup.bat` once with internet access. Use `tools/Start Server.bat` to run. Setup creates a local `.venv` dependency folder, which is generated machinery rather than project code.

Manual equivalent from this Source folder:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe server.py
```

Use `--port 8080` to change the port or `--no-browser` to suppress automatic browser opening.

## Room connection choice

Before creating a room, choose **Wi-Fi / LAN** or **Tailscale** in the host form. This choice stays fixed for the room, including rematches. Create a new room to change it. The host status and address are rechecked by the server at creation. With multiple interfaces, choose the host network address from the dropdown.

Copy Invite uses that room's chosen server address, even if the host opened localhost. Tailscale must be installed and connected on the host and on participating remote players' devices. The selector does not install/connect Tailscale, change firewall rules, or disable the other network interface. It chooses the advertised join address. The server does not move between PCs.

## Game rules

- 2-5 starting players, N turns and N distinct words from the host's chosen theme. Each player draws once in randomized order.
- 80 seconds per turn. Hint letters appear at 60, 40, and 20 seconds remaining.
- Guess placement earns 100 / 80 / 50 / 45 points, in server acceptance order.
- Drawer earns 20 per unsuccessful remaining guesser. Honest drawing is a player agreement.
- Case and outer whitespace do not matter. Word boundaries do: `icecream` is close; `ice cream` is correct. Near misses use a similarity heuristic.
- Correct answers stay out of public chat. Drawer and successful guessers cannot chat during the turn.
- Everyone correct or time expired ends a turn. Five-second breaks reveal the answer. Total points determine final ranks; ties share ranks.
- Detected unexpected disconnects freeze play. Host waits or continues without the player. Same-tab tokens restore sessions.
- Host-player control can transfer; the actual server does not migrate. Removing the drawer skips the turn without bonus; fewer than two remaining players ends the game.
- Rooms/scores are in memory. Restarting loses sessions. New players join only waiting or finished rooms.

## Sound and appearance

Top-right controls switch light/dark mode and mute. Avatar, mute, and theme preferences are saved per browser/server address. Canvas stays white. Sounds are synthesized offline after a user gesture. Ticking starts at 20 seconds, speeds up in the last 8, and stops during pauses, after your correct guess, or on turn end. Reduced-motion preferences disable decorative animation.

## Rebuild the executable

If you change the source, rebuild on Windows x64 using an environment with Python and the required libraries installed:

```powershell
python -m pip install -r requirements.txt pyinstaller
python tools/build_portable.py
```

The builder updates `GuessTheMess.exe` in the parent folder and automatically removes its temporary build files. It does not install libraries or run Setup.bat for you.

The EXE embeds Python and dependencies and extracts them temporarily at launch. It needs no adjacent support folder. **Editing source does not update the existing EXE:** run the source or rebuild after changes.

The server discovers this computer's addresses at launch. No previous IP address, room, chat log, score history, or player database is stored in the project files.
