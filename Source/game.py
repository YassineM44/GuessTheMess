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
PICK_SECONDS = 10.0
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
        self.word_pool, self.word_choices = [], []
        self.used_words = set()
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

    def join(self, name, avatar="👾"):
        """Restore a disconnected reserved nickname, or register in a lobby.

        Room registration is nickname-based, not password authentication.
        A normal Join must also work if the returning browser lost its token.
        Connected and explicitly skipped seats cannot be reclaimed this way.
        """
        if self.phase in ("lobby", "finished"):
            return self.add(name, avatar)
        name_key = normalize(name)
        player = next((p for p in self.members() if normalize(p.name) == name_key), None)
        if player is None:
            skipped = any(p.id in self.order and not p.active and normalize(p.name) == name_key
                          for p in self.players.values())
            if skipped:
                raise ValueError("The host skipped your seat. Join again after this game finishes.")
            raise ValueError("This game has started. Only returning players with a reserved seat can rejoin.")
        if player.connected or player.id not in self.pause_for:
            raise ValueError("That player is already connected. Use their open game tab.")
        self.reconnect(player.id)
        # The newly restored browser receives fresh reconnect credentials.
        player.token = secrets.token_urlsafe(32)
        return player

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
        self.word_pool = list(dict.fromkeys(self.word_lists[self.theme]))
        if len(self.word_pool) < len(members) + 2:
            raise ValueError("This theme needs enough words to offer three unused choices each turn.")
        self.words = [""] * len(members)
        self.used_words.clear()
        self.word_choices = []
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
            self.word_choices = []
            self.pause_for.clear()
            self.system("Game complete! Check the final podium.")
            return
        self.phase = "picking"
        self.turn_id = secrets.token_hex(8)
        self.remaining = PICK_SECONDS
        self.word_choices = random.sample([w for w in self.word_pool if w not in self.used_words], 3)
        self.guessed, self.revealed = [], set()
        self.ops, self.op_ids = [], set()
        self.points_used = 0
        self.events.append({"type": "canvas", "turn": self.turn_id, "ops": []})
        self.system(f"{self.players[self.drawer].name} is picking a word!")

    def choose_word(self, pid, turn, word):
        if self.pause_for:
            raise ValueError("The game is paused. Wait for reconnection or the host's decision.")
        if self.phase != "picking" or turn != self.turn_id:
            raise ValueError("That word selection has ended.")
        if pid != self.drawer or not self.players[pid].connected or not self.players[pid].active:
            raise ValueError("Only the current drawer can choose the word.")
        if not isinstance(word, str) or word not in self.word_choices:
            raise ValueError("Choose one of the three offered words.")
        self.words[self.index] = word
        self.used_words.add(word)
        self.word_choices = []
        self.phase, self.remaining = "drawing", TURN_SECONDS
        self.system(f"{self.players[self.drawer].name} is drawing. Guess in chat!")

    def finish_turn(self, skipped=False):
        if self.phase != "drawing" and not (skipped and self.phase == "picking"):
            return
        missed = [pid for pid in self.eligible() if pid not in self.guessed]
        bonus = 0 if skipped else 20 * len(missed)
        drawer = self.players[self.drawer]
        drawer.score += bonus
        self.last_result = {"word": self.answer, "drawer": drawer.name, "bonus": bonus,
                            "guessed": len(self.guessed), "skipped": skipped}
        self.phase, self.remaining = "intermission", BREAK_SECONDS
        self.word_choices = []
        if skipped:
            self.system(f"{drawer.name}'s turn was skipped." + (f' The word was “{self.answer}”.' if self.answer else ""))
        else:
            self.system(f'The word was “{self.answer}”. {drawer.name} earned {bonus} drawing points.')

    def guess(self, pid, text):
        p = self.players[pid]
        if self.pause_for:
            raise ValueError("The game is paused.")
        if not p.active or not p.connected:
            raise ValueError("You are not in this game.")
        if self.phase == "picking":
            raise ValueError("Wait until the drawer picks a word before chatting or guessing.")
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
        if self.pause_for or self.phase not in ("picking", "drawing", "intermission"):
            return
        self.remaining = max(0, self.remaining - dt)
        if self.phase == "picking":
            if self.remaining == 0:
                self.choose_word(self.drawer, self.turn_id, random.choice(self.word_choices))
            return
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
        running = self.phase in ("picking", "drawing", "intermission")
        if running:
            self.pause_for.add(pid)
            reason = "left the room" if voluntary else "disconnected"
            self.system(f"{p.name} {reason}. Seat reserved; game frozen until they return or the host skips them.")
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
        p.rtc_ready = False
        if self.phase in ("picking", "drawing", "intermission"):
            self.pause_for.add(pid)
        if self.host is None:
            self.host = pid
        self.system(f"{p.name} reconnected. Restoring their drawing connection…")

    def drawing_connection(self, pid, ready):
        """A resumed player stays paused until both transport channels work."""
        p = self.players[pid]
        if not p.active or (ready and not p.connected):
            return
        p.rtc_ready = ready
        if ready:
            returning = pid in self.pause_for
            self.pause_for.discard(pid)
            if returning:
                self.system(f"{p.name}'s connections are restored.")
        elif p.connected and self.phase in ("picking", "drawing", "intermission"):
            if pid not in self.pause_for:
                self.pause_for.add(pid)
                self.system(f"{p.name} lost their drawing connection. Game frozen; repair it or ask the host to skip them.")

    def drop(self, pid):
        self.players[pid].active = False
        self.pause_for.discard(pid)
        if self.phase in ("picking", "drawing"):
            if pid == self.drawer:
                self.finish_turn(skipped=True)
            elif self.phase == "drawing" and all(x in self.guessed for x in self.eligible()):
                self.finish_turn()
        if self.host == pid:
            other = next((p for p in self.members() if p.connected), None)
            self.host = other.id if other else None
            if other:
                self.system(f"{other.name} is now the room host.")
        if self.phase in ("picking", "drawing", "intermission") and len(self.members()) < MIN_PLAYERS:
            self.phase = "finished"
            self.word_choices = []
            self.pause_for.clear()
            self.system("Not enough players remain. Game ended.")

    def continue_without(self, pid):
        if pid != self.host:
            raise ValueError("Only the host can continue without disconnected players.")
        missing_players = list(self.pause_for)
        for missing in missing_players:
            self.system(f"Continuing without {self.players[missing].name}.")
            self.drop(missing)
        return missing_players

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
                "pick_seconds": PICK_SECONDS,
                "choices": list(self.word_choices) if self.phase == "picking" and pid == self.drawer else [],
                "mask": "".join(c if c == " " or i in self.revealed else "_"
                                for i, c in enumerate(self.answer)) if self.phase == "drawing" else "",
                "word": self.answer if pid == self.drawer and self.phase == "drawing" else None,
                "paused": [self.players[x].name for x in self.pause_for],
                "result": self.last_result if self.phase != "drawing" else None,
                "ranking": ranking}
