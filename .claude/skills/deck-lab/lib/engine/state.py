"""The game state: flat, and built to be copied.

`clone()` is the primitive search spends its time on — the fastest Hearthstone
engines advertise clones per second, not rules per second — so the shape here is
chosen for copying rather than for elegance:

* **No object graph.** A unit is a plain `dict` of primitives with an id; nothing
  points at anything else. Copying the board is `[dict(u) for u in units]`, which
  is a C-level loop, where a graph of `Permanent` objects would need `deepcopy`
  (the table measures ~890 of those a second).
* **The generator is an integer.** See `rng.py`.
* **Zones are lists of card names.** A card in a deck, a hand or a trash has no
  identity that any rule can observe, so it does not get one. Only objects on
  the Board and items on the Chain have ids, because rules talk about those.

The one thing the shape is NOT chosen for is being pretty to read. `u["loc"]`
instead of `unit.location` is the price of the clone rate, and `view()` exists so
that nothing outside the kernel has to read the raw structure.
"""
import hashlib

import cards

BASE = "base"
BATTLEFIELD = "bf"

#: Phases and steps of a turn (314-317), plus the two pseudo-phases that bracket
#: the game: `setup` (110-118) and `over`.
SETUP, AWAKEN, BEGINNING, CHANNEL, DRAW, MAIN, ENDING, OVER = (
    "setup", "awaken", "beginning", "channel", "draw", "main", "ending", "over",
)


class RulesError(Exception):
    """An action the rules do not allow. Raised instead of quietly proceeding.

    Shares a name with the table's exception on purpose: the two are the same
    idea, and `deck_cli` already turns one into a single readable line.
    """


def new_unit(oid, name, controller, location, exhausted):
    """A permanent on the Board (140, 147).

    `might` is cached at creation rather than looked up per read: combat sums it
    once per unit per damage step, and the lookup is a dict miss away from being
    the hottest line in the engine.
    """
    return {
        "id": oid,
        "name": name,
        "ctrl": controller,
        "owner": controller,
        "loc": location,
        "exh": exhausted,
        "dmg": 0,
        "buffs": 0,
        "might": cards.might(name) or 0,
        "unit": cards.card_type(name) == cards.UNIT,
    }


def new_rune(oid, name, controller, exhausted):
    """A channeled rune (161.1.a — on the board, but not a permanent)."""
    domains = cards.domains(name)
    return {
        "id": oid,
        "name": name,
        "ctrl": controller,
        "exh": exhausted,
        "domain": domains[0] if domains else None,
    }


def new_battlefield(index, name, provided_by):
    """A battlefield in the Battlefield Zone (169), and who holds it (190)."""
    return {
        "i": index,
        "name": name,
        "by": provided_by,
        "ctrl": None,
        #: 190.3.a. `contested_by` is kept because two separate rules need it and
        #: neither can recover it from a bool: 464.2.c.1 makes that player the
        #: Attacker, and 323.11 makes removal depend on whether they still have
        #: units here.
        "contested": False,
        "contested_by": None,
        #: Seats that have already Scored here this turn (470).
        "scored": [],
        #: 323.8 / 323.9. Staged is not the same as ongoing: a Showdown is marked
        #: Staged in the cleanup after Contested is applied, and only opens later,
        #: in a Neutral Open State, at a battlefield the Turn Player chooses.
        "sd_staged": False,
        "cb_staged": False,
    }


class State:
    """Everything the rules can observe. Nothing else."""

    __slots__ = (
        "seed", "seat_rng", "shared_rng",
        "hand", "main_deck", "rune_deck", "trash", "banished", "champion",
        "points", "energy", "power",
        "units", "runes", "battlefields",
        "turn", "phase", "turn_player", "first_player", "second_channel_used",
        "victory_target", "winner", "end_reason",
        "chain", "priority", "passes", "showdown", "resolve_now",
        "tasks", "choosing", "pending", "next_id", "cleanups", "combat_recalled",
    )

    def __init__(self):
        self.seed = 0
        self.seat_rng = [0, 0]
        self.shared_rng = 0
        self.hand = [[], []]
        self.main_deck = [[], []]
        self.rune_deck = [[], []]
        self.trash = [[], []]
        self.banished = [[], []]
        self.champion = [[], []]
        self.points = [0, 0]
        self.energy = [0, 0]
        self.power = [{}, {}]
        self.units = []
        self.runes = []
        self.battlefields = []
        self.turn = 0
        self.phase = SETUP
        self.turn_player = 0
        self.first_player = 0
        self.second_channel_used = False
        self.victory_target = 8
        self.winner = None
        #: The rule that ended the game, so the log names one. A game that stops
        #: for any other reason is a bug, and the soak test says so.
        self.end_reason = ""
        #: Oldest item first, so `chain[-1]` is the newest — which is the one
        #: 340.1 resolves. The Chain is a stack read from the right.
        self.chain = []
        self.priority = None
        #: Consecutive passes with nothing added to the Chain (339.1).
        self.passes = 0
        self.showdown = None
        #: 337.2 fired: the item just finalized is a Unit, Gear or an Add
        #: ability, so the next FEPR step is Resolve rather than Finalize.
        self.resolve_now = False
        #: Set by the Combat Special Cleanup's inserted step 3d (466.1.a.2) so
        #: the Resolution Step can tell a repel (No Result, 466.3.d) from a side
        #: that was simply wiped out.
        self.combat_recalled = False
        #: Outstanding Tasks (333), oldest first. `tasks[0]` is next. New Tasks
        #: incurred partway through a process go to the FRONT, which is 334.2.a:
        #: complete the current step, then pause and complete the new Task.
        self.tasks = []
        #: The first half of a grouped decision, waiting for its second half.
        self.choosing = None
        #: The question the kernel has stopped on, or None.
        self.pending = None
        self.next_id = 1
        #: How many cleanups have run back to back without the state settling
        #: (322). A bound, so a rule that fights itself is a loud failure.
        self.cleanups = 0

    # -- copying ---------------------------------------------------------

    def clone(self):
        """A deep-enough copy: nothing in the copy aliases anything mutable."""
        s = State.__new__(State)
        s.seed = self.seed
        s.seat_rng = self.seat_rng[:]
        s.shared_rng = self.shared_rng
        s.hand = [self.hand[0][:], self.hand[1][:]]
        s.main_deck = [self.main_deck[0][:], self.main_deck[1][:]]
        s.rune_deck = [self.rune_deck[0][:], self.rune_deck[1][:]]
        s.trash = [self.trash[0][:], self.trash[1][:]]
        s.banished = [self.banished[0][:], self.banished[1][:]]
        s.champion = [self.champion[0][:], self.champion[1][:]]
        s.points = self.points[:]
        s.energy = self.energy[:]
        s.power = [dict(self.power[0]), dict(self.power[1])]
        s.units = [dict(u) for u in self.units]
        s.runes = [dict(r) for r in self.runes]
        s.battlefields = [_copy_bf(b) for b in self.battlefields]
        s.turn = self.turn
        s.phase = self.phase
        s.turn_player = self.turn_player
        s.first_player = self.first_player
        s.second_channel_used = self.second_channel_used
        s.victory_target = self.victory_target
        s.winner = self.winner
        s.end_reason = self.end_reason
        s.chain = [dict(c) for c in self.chain]
        s.priority = self.priority
        s.passes = self.passes
        s.showdown = dict(self.showdown) if self.showdown else None
        s.resolve_now = self.resolve_now
        s.combat_recalled = self.combat_recalled
        s.tasks = self.tasks[:]
        # Both of these carry a LIST, and `dict(x)` copies neither. A shallow
        # copy here meant `clone().s.pending["options"].append(...)` added an
        # option to the original's decision — a search node handing the real
        # game an illegal move, silently. Anything reachable from the state is
        # copied; nothing shared is mutable.
        s.choosing = _copy_choice(self.choosing)
        s.pending = _copy_pending(self.pending)
        s.next_id = self.next_id
        s.cleanups = self.cleanups
        return s

    # -- queries ---------------------------------------------------------

    def opponent(self, seat):
        return 1 - seat

    def turn_order(self, start=None):
        """Seats in Turn Order from `start`, defaulting to the Turn Player.

        303.2.a: nothing in this game happens simultaneously, and when several
        things must happen at once Turn Order decides the sequence "starting
        with the current Turn Player". Every loop over both players in this
        kernel goes through here, and that is what makes a mirrored game an
        exact mirror: a loop over `range(2)` bakes the seat NUMBERS into the
        order of events, so swapping who goes first changes the game.
        """
        first = self.turn_player if start is None else start
        return (first, 1 - first)

    def unit(self, oid):
        for u in self.units:
            if u["id"] == oid:
                return u
        raise RulesError("no object with id %r on the board" % (oid,))

    def at(self, location):
        return [u for u in self.units if u["loc"] == location]

    def units_at(self, location, seat=None):
        return [u for u in self.units
                if u["loc"] == location and u["unit"]
                and (seat is None or u["ctrl"] == seat)]

    def battlefield(self, index):
        try:
            return self.battlefields[int(index)]
        except (IndexError, ValueError, TypeError):
            raise RulesError("no battlefield %r" % (index,))

    def seats_at(self, index):
        bf = self.battlefields[index]
        return set(u["ctrl"] for u in self.units_at(loc_bf(index)))

    def might_of(self, unit):
        """Printed Might plus buffs (703). Damage does not reduce Might."""
        return unit["might"] + unit["buffs"]

    # -- the four states of the turn (307-310) ---------------------------

    def is_closed(self):
        """309.1: a Chain exists."""
        return bool(self.chain)

    def is_showdown(self):
        """308.1: a Showdown or Combat is in progress."""
        return self.showdown is not None

    def turn_state(self):
        """One of the four combined states of 310, as a string for the log."""
        return "%s-%s" % (
            "showdown" if self.is_showdown() else "neutral",
            "closed" if self.is_closed() else "open",
        )

    # -- identity --------------------------------------------------------

    def mint(self, prefix):
        """A fresh object id, never one already on the board.

        The counter alone would do; the scan is belt and braces because an id
        collision is silent and mis-targets a kill, which the table found worth
        two guards.
        """
        taken = set(o["id"] for o in self.units)
        taken.update(r["id"] for r in self.runes)
        while True:
            oid = "%s%d" % (prefix, self.next_id)
            self.next_id += 1
            if oid not in taken:
                return oid

    # -- hashing ---------------------------------------------------------

    def canonical(self):
        """The whole state as nested primitives, in a fixed order.

        Fixed order rather than "whatever the dict iterates" — a hash that
        depends on insertion order compares two games by how they were built
        instead of by what they are.
        """
        return (
            self.turn, self.phase, self.turn_player, self.first_player,
            self.second_channel_used, self.victory_target, self.winner,
            self.end_reason, self.priority, self.passes, self.turn_state(),
            tuple(self.points), tuple(self.energy),
            tuple(tuple(sorted(p.items())) for p in self.power),
            tuple(tuple(z) for z in self.hand),
            tuple(tuple(z) for z in self.main_deck),
            tuple(tuple(z) for z in self.rune_deck),
            tuple(tuple(z) for z in self.trash),
            tuple(tuple(z) for z in self.banished),
            tuple(tuple(z) for z in self.champion),
            tuple((u["id"], u["name"], u["ctrl"], u["owner"], u["loc"],
                   u["exh"], u["dmg"], u["buffs"]) for u in self.units),
            tuple((r["id"], r["name"], r["ctrl"], r["exh"]) for r in self.runes),
            tuple((b["i"], b["name"], b["by"], b["ctrl"], b["contested"],
                   b["contested_by"], tuple(b["scored"]), b["sd_staged"],
                   b["cb_staged"]) for b in self.battlefields),
            tuple((c["id"], c["ctrl"], c["name"], c["kind"], c["pending"],
                   c["loc"]) for c in self.chain),
            None if self.showdown is None else (
                self.showdown["bf"], self.showdown["combat"],
                self.showdown["focus"], self.showdown["passes"],
                self.showdown["closed"]),
            self.resolve_now, self.combat_recalled,
            tuple(self.tasks),
            tuple(sorted(self.choosing.items())) if self.choosing else None,
            tuple(self.seat_rng), self.shared_rng,
        )

    def hash(self):
        """A short digest of the whole state, stable across processes.

        blake2b over `repr(canonical())`, not `hash()`: Python salts string
        hashing per interpreter, so a golden recorded today would not reproduce
        tomorrow.
        """
        return hashlib.blake2b(
            repr(self.canonical()).encode("utf-8"), digest_size=8).hexdigest()


def _copy_bf(b):
    c = dict(b)
    c["scored"] = b["scored"][:]
    return c


def _copy_pending(p):
    """A pending decision that shares nothing mutable with the one it came from.

    `options` is a list of (key, label) pairs. The pairs are tuples of
    primitives and cannot be mutated; the LIST can, so it is the one thing that
    has to be copied.
    """
    if p is None:
        return None
    copy = dict(p)
    copy["options"] = list(p["options"])
    return copy


def _copy_choice(c):
    """The half-made choice, with any list in it copied.

    Written over the values rather than over a list of known keys: `choosing`
    grows a field every time a new grouped decision is added, and a copy that
    knows the field names is a copy that silently stops being deep the next time
    one appears.
    """
    if c is None:
        return None
    copy = dict(c)
    for key, value in copy.items():
        if isinstance(value, list):
            copy[key] = value[:]
        elif isinstance(value, dict):
            copy[key] = dict(value)
    return copy


# -- locations -----------------------------------------------------------

def loc_base(seat):
    return "%s:%d" % (BASE, seat)


def loc_bf(index):
    return "%s:%d" % (BATTLEFIELD, index)


def is_bf(location):
    return location.startswith(BATTLEFIELD + ":")


def bf_index(location):
    return int(location.split(":")[1])


def where(state, location):
    """A location as a person reads it."""
    kind, _, idx = location.partition(":")
    if kind == BASE:
        return "seat %s's base" % idx
    return "%s (bf:%s)" % (state.battlefield(idx)["name"], idx)


# -- the information set -------------------------------------------------

def public_view(state):
    """What anyone may see: both seats' public zones, and no hand at all.

    The terminal decision goes to whoever is holding the game, which is not a
    seat — building it from `view(state, 0)` handed seat 0's hand to seat 1's
    policy at the one moment nobody checks the contents.
    """
    out = view(state, 0)
    del out["seat"]
    mine = out.pop("you")
    mine.pop("hand", None)
    out["seats"] = [mine, out.pop("opponent")]
    return out


def view(state, seat):
    """What `seat` may see: its own hand, every public zone, sizes of the rest.

    108.7.c makes a hand Private Information, and the whole point of putting
    determinization in the engine (`Game.apply_seed`) is that a policy reads
    THIS and never the state. So the opponent's hand appears here as a count and
    its decks as counts, and nothing that is hidden leaks through.
    """
    other = 1 - seat

    def public(s):
        return {
            "points": state.points[s],
            "energy": state.energy[s],
            "power": dict(state.power[s]),
            "trash": state.trash[s][:],
            "banished": state.banished[s][:],
            "champion": state.champion[s][:],
            "hand_size": len(state.hand[s]),
            "main_deck_size": len(state.main_deck[s]),
            "rune_deck_size": len(state.rune_deck[s]),
        }

    mine = public(seat)
    mine["hand"] = state.hand[seat][:]
    return {
        "seat": seat,
        "turn": state.turn,
        "phase": state.phase,
        "turn_player": state.turn_player,
        "first_player": state.first_player,
        "turn_state": state.turn_state(),
        "victory_target": state.victory_target,
        "winner": state.winner,
        "end_reason": state.end_reason,
        "you": mine,
        "opponent": public(other),
        "units": [dict(u) for u in state.units],
        "runes": [dict(r) for r in state.runes],
        "battlefields": [_copy_bf(b) for b in state.battlefields],
        "chain": [dict(c) for c in state.chain],
        "showdown": dict(state.showdown) if state.showdown else None,
    }
