"""Socket-independent, server-authoritative game rules."""
import random
import re
import secrets
import time
from dataclasses import dataclass, field
from difflib import SequenceMatcher

POINTS = (100, 80, 50, 45)
MIN_PLAYERS = 2
MAX_PLAYERS = 5
AVATARS = ("👾", "🐸", "🦊", "🐼", "🐙", "👻", "🤖", "🌵")
TURN_SECONDS = 80.0
BREAK_SECONDS = 5.0


def normalize(text):
    # Internal word boundaries matter; repeated whitespace does not.
    return " ".join(text.strip().casefold().split())


def close_guess(guess, answer):
    a, b = normalize(guess), normalize(answer)
    return a != b and (a.replace(" ", "") == b.replace(" ", "") or
                       (len(a) >= 3 and SequenceMatcher(None, a, b).ratio() >= .78))


@dataclass
class Player:
    id: str
    name: str
    token: str = field(default_factory=lambda: secrets.token_urlsafe(32))
    score: int = 0
    connected: bool = True
    active: bool = True
    rtc_ready: bool = False
    last_chat: float = 0
    avatar: str = "👾"


class Room:
    def __init__(self, code, name, theme, words, connection_mode="lan", invite_base=""):
        self.code, self.name, self.theme = code, name, theme
        self.word_lists = words
        self.connection_mode = connection_mode
        self.invite_base = invite_base
        self.players = {}
        self.host = None
        self.phase = "lobby"
        self.order, self.words = [], []
        self.index = -1
        self.turn_id = ""
        self.remaining = 0.0
        self.guessed = []
        self.revealed = set()
        self.pause_for = set()
        self.ops = []
        self.op_ids = set()
        self.points_used = 0
        self.events = []
        self.last_result = None
        self.last_active = time.monotonic()

    def add(self, name, avatar="👾"):
        name = re.sub(r"\s+", " ", name.strip())
        if not 1 <= len(name) <= 20 or any(ord(c) < 32 for c in name):
            raise ValueError("Choose a username of 1–20 characters.")
        if self.phase not in ("lobby", "finished"):
            raise ValueError("This game has started. Join after it finishes.")
        if len(self.members()) >= MAX_PLAYERS:
            raise ValueError("This room is full (five players maximum).")
        if any(p.active and normalize(p.name) == normalize(name) for p in self.players.values()):
            raise ValueError("That username is already in this room.")
        p = Player(secrets.token_hex(8), name, avatar=avatar if avatar in AVATARS else AVATARS[0])
        self.players[p.id] = p
        if self.host is None:
            self.host = p.id
        self.system(f"{name} joined the room.")
        return p

    def members(self):
        return [p for p in self.players.values() if p.active]

    @property
    def drawer(self):
        return self.order[self.index] if 0 <= self.index < len(self.order) else None

    @property
    def answer(self):
        return self.words[self.index] if 0 <= self.index < len(self.words) else ""

    def eligible(self):
        return [p.id for p in self.members() if p.id != self.drawer and p.id in self.order]

    def system(self, message):
        self.events.append({"type": "chat", "kind": "system", "text": message})

    def start(self, pid):
        if pid != self.host:
            raise ValueError("Only the host can start the game.")
        if self.phase not in ("lobby", "finished"):
            raise ValueError("A game is already running.")
        members = self.members()
        if not MIN_PLAYERS <= len(members) <= MAX_PLAYERS:
            raise ValueError(f"You need {MIN_PLAYERS}–{MAX_PLAYERS} players to start.")
        if not all(p.connected and p.rtc_ready for p in members):
            raise ValueError("Wait until every player has a green UDP connection.")
        self.order = [p.id for p in members]
        random.shuffle(self.order)
        self.words = random.sample(self.word_lists[self.theme], len(members))
        for p in members:
            p.score = 0
        self.pause_for.clear()
        self.index = -1
        self.last_result = None
        self.next_turn()

    def next_turn(self):
        self.index += 1
        while self.index < len(self.order) and not self.players[self.order[self.index]].active:
            self.index += 1
        if self.index >= len(self.order) or len(self.members()) < MIN_PLAYERS:
            self.phase = "finished"
            self.system("Game complete! Check the final podium.")
            return
        self.phase = "drawing"
        self.turn_id = secrets.token_hex(8)
        self.remaining = TURN_SECONDS
        self.guessed, self.revealed = [], set()
        self.ops, self.op_ids = [], set()
        self.points_used = 0
        self.events.append({"type": "canvas", "turn": self.turn_id, "ops": []})
        self.system(f"{self.players[self.drawer].name} is drawing. Guess in chat!")

    def finish_turn(self, skipped=False):
        if self.phase != "drawing":
            return
        missed = [pid for pid in self.eligible() if pid not in self.guessed]
        bonus = 0 if skipped else 20 * len(missed)
        drawer = self.players[self.drawer]
        drawer.score += bonus
        self.last_result = {"word": self.answer, "drawer": drawer.name, "bonus": bonus,
                            "guessed": len(self.guessed), "skipped": skipped}
        self.phase, self.remaining = "intermission", BREAK_SECONDS
        self.system(f'The word was “{self.answer}”. {drawer.name} earned {bonus} drawing points.'
                    if not skipped else f'Turn skipped. The word was “{self.answer}”.')

    def guess(self, pid, text):
        p = self.players[pid]
        if self.pause_for:
            raise ValueError("The game is paused.")
        if not p.active or not p.connected:
            raise ValueError("You are not in this game.")
        text = text.strip()
        if not 1 <= len(text) <= 200:
            raise ValueError("Messages must contain 1–200 characters.")
        if self.phase == "drawing":
            if pid == self.drawer:
                raise ValueError("The drawer cannot chat during their turn.")
            if pid in self.guessed:
                raise ValueError("You already guessed! Chat returns next turn.")
        now = time.monotonic()
        if now - p.last_chat < .45:
            raise ValueError("Give your guesses a moment between messages.")
        p.last_chat = now
        if self.phase == "drawing" and normalize(text) == normalize(self.answer):
            points = POINTS[len(self.guessed)]
            self.guessed.append(pid)
            p.score += points
            self.events.append({"type": "chat", "kind": "correct", "text":
                                f"{p.name} guessed it! #{len(self.guessed)} · +{points} points",
                                "player": pid, "name": p.name, "avatar": p.avatar,
                                "points": points, "place": len(self.guessed)})
            if all(x in self.guessed for x in self.eligible()):
                self.finish_turn()
            return {"type": "notice", "text": f"Correct! +{points} points.", "success": True, "effect": "correct"}
        # Near misses stay private so a spacing typo cannot reveal the answer.
        if self.phase == "drawing" and close_guess(text, self.answer):
            return {"type": "notice", "text": "Close one! Check your spelling and spaces.", "effect": "close"}
        self.events.append({"type": "chat", "kind": "message", "name": p.name, "text": text,
                            "player": pid, "avatar": p.avatar, "guess": self.phase == "drawing"})
        return {"type": "feedback", "effect": "wrong"} if self.phase == "drawing" else None

    def tick(self, dt):
        if self.pause_for or self.phase not in ("drawing", "intermission"):
            return
        self.remaining = max(0, self.remaining - dt)
        if self.phase == "intermission":
            if self.remaining == 0:
                self.next_turn()
            return
        count = sum(self.remaining <= mark for mark in (60, 40, 20))
        # Always leave at least one letter unknown, even for future short words.
        target = min(count, max(0, sum(c.isalpha() for c in self.answer) - 1))
        while len(self.revealed) < target:
            options = [i for i, c in enumerate(self.answer) if c.isalpha() and i not in self.revealed]
            self.revealed.add(random.choice(options))
        if self.remaining == 0:
            self.finish_turn()

    def disconnect(self, pid, voluntary=False):
        p = self.players[pid]
        p.connected, p.rtc_ready = False, False
        running = self.phase in ("drawing", "intermission")
        if running and not voluntary:
            self.pause_for.add(pid)
            self.system(f"{p.name} disconnected. Game frozen; the host can wait or continue.")
        else:
            self.drop(pid)
        if self.host == pid:
            other = next((x for x in self.members() if x.connected), None)
            self.host = other.id if other else None
            if other:
                self.system(f"{other.name} is now the room host.")

    def reconnect(self, pid):
        p = self.players[pid]
        if not p.active:
            raise ValueError("The host continued without you. Join again after this game.")
        p.connected = True
        self.pause_for.discard(pid)
        if self.host is None:
            self.host = pid
        self.system(f"{p.name} reconnected.")

    def drop(self, pid):
        self.players[pid].active = False
        self.pause_for.discard(pid)
        if self.phase == "drawing":
            if pid == self.drawer:
                self.finish_turn(skipped=True)
            elif all(x in self.guessed for x in self.eligible()):
                self.finish_turn()
        if self.phase in ("drawing", "intermission") and len(self.members()) < MIN_PLAYERS:
            self.phase = "finished"
            self.system("Not enough players remain. Game ended.")

    def continue_without(self, pid):
        if pid != self.host:
            raise ValueError("Only the host can continue without disconnected players.")
        for missing in list(self.pause_for):
            self.system(f"Continuing without {self.players[missing].name}.")
            self.drop(missing)

    def can_draw(self, pid, turn):
        return (self.phase == "drawing" and not self.pause_for and pid == self.drawer
                and turn == self.turn_id and self.players[pid].active
                and self.players[pid].connected)

    def state(self, pid):
        ranks = sorted(self.members(), key=lambda p: -p.score)
        ranking, last_score, rank = [], None, 0
        for i, p in enumerate(ranks):
            if p.score != last_score:
                rank = i + 1
            last_score = p.score
            ranking.append({"id": p.id, "name": p.name, "score": p.score, "rank": rank, "avatar": p.avatar})
        return {"type": "state", "code": self.code, "name": self.name, "theme": self.theme,
                "connection_mode": self.connection_mode,
                "invite_url": f"{self.invite_base}/?room={self.code}" if self.invite_base else "",
                "min_players": MIN_PLAYERS, "max_players": MAX_PLAYERS,
                "phase": self.phase, "host": self.host, "you": pid,
                "players": [{"id": p.id, "name": p.name, "score": p.score, "avatar": p.avatar,
                             "connected": p.connected, "udp": p.rtc_ready,
                             "guessed": p.id in self.guessed} for p in self.members()],
                "drawer": self.drawer, "turn": self.turn_id,
                "round": min(self.index + 1, len(self.order)), "rounds": len(self.order),
                "remaining": round(self.remaining, 1),
                "mask": "".join(c if c == " " or i in self.revealed else "_"
                                for i, c in enumerate(self.answer)) if self.phase == "drawing" else "",
                "word": self.answer if pid == self.drawer and self.phase == "drawing" else None,
                "paused": [self.players[x].name for x in self.pause_for],
                "result": self.last_result if self.phase != "drawing" else None,
                "ranking": ranking}
