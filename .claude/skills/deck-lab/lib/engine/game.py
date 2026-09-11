"""`Game` — the object a policy, a search or a person actually holds.

    game = Game.new(deck_a, deck_b, seed=7)
    while True:
        d = game.step()
        if d.terminal:
            break
        game.answer(policy[d.seat](d))

`step()` runs the rules until a choice is needed. `answer()` takes one of the
options it offered and refuses anything else. `clone()` copies the position.
`apply_seed()` turns the position into one full-information world consistent
with what a seat has seen. Everything else in this package is what those four
methods call.

**Determinization lives here, not in the search.** Scripts of Tribute's engine
does the same thing and it is the right split: a searcher that samples hidden
information itself will sample it differently from the way the rules deal it,
and the resulting worlds are subtly impossible. `apply_seed(seat, seed)` returns
a Game whose public facts are untouched, whose `seat` hand is untouched, whose
hidden zone SIZES are untouched, and whose hidden cards have been redealt.
"""
import deckfile

from . import actions, chain, rng, turn
from .decisions import Decision, Option, terminal
from .state import (ENDING, MAIN, OVER, SETUP, RulesError, State, loc_base,
                    loc_bf, view)


def _id_number(oid):
    digits = "".join(ch for ch in str(oid) if ch.isdigit())
    return int(digits) if digits else 0


class Game:
    """One game, and the decision-request API over it."""

    #: 117.1 caps a mulligan at two cards.
    MULLIGAN_MAX = 2
    #: A `step()` that runs this many mandatory operations without reaching a
    #: decision is not working, it is spinning. A bound turns a hang into a
    #: named failure, which is the difference between a bug you can find and a
    #: CI job that times out.
    MAX_TICKS = 20000
    #: Likewise for a game that never ends. Well above any real game: the
    #: longest random-vs-random game measured is under 60 turns.
    MAX_TURNS = 400

    __slots__ = ("decks", "mode", "s", "log", "auto_trivial", "hash_log",
                 "decisions", "check_invariants")

    def __init__(self, decks, state, mode, log, auto_trivial=True, hash_log=True,
                 check_invariants=False):
        self.decks = decks
        self.mode = mode
        self.s = state
        self.log = log
        #: Run `invariants.check` after every mandatory operation. Costs about a
        #: third of the throughput, so it is off by default and on wherever
        #: correctness is what is being measured.
        self.check_invariants = check_invariants
        #: A decision with exactly one legal option is not a decision. Taking it
        #: automatically keeps a policy from being asked 400 questions with one
        #: answer each; the log is identical either way, which `selftest` pins,
        #: so this is a speed setting and never a rules setting.
        self.auto_trivial = auto_trivial
        #: Stamp every log entry with the state hash. Auditable by default; off
        #: for perft and soak runs, where the log is never read.
        self.hash_log = hash_log
        self.decisions = 0

    # -- construction ----------------------------------------------------

    @classmethod
    def new(cls, deck_a, deck_b, seed=1, first=None, seat_seeds=None,
            mode=None, auto_trivial=True, hash_log=True, invariants=False):
        """A new game. Deterministic: the same arguments replay exactly.

        `first` decides who goes first; left out, it is drawn from the shared
        stream (115, "any fair random method"). `seat_seeds` overrides the two
        per-seat streams, which is what the perfect-symmetry test needs — it
        plays the same deck on both seats with the streams swapped and the first
        player swapped, and the two games must be exact mirrors.
        """
        mode = mode or deckfile.MODE
        s = State()
        s.seed = seed
        s.shared_rng = rng.seed_from(seed)
        s.seat_rng = list(seat_seeds) if seat_seeds else [
            rng.seat_seed(seed, 0), rng.seat_seed(seed, 1)]
        s.victory_target = mode["victory_score"]
        if first is None:
            # 115: any fair random method, on the shared stream, so who goes
            # first is a property of the seed and not of either deck.
            s.shared_rng, first = rng.below(s.shared_rng, 2)
        s.first_player = int(first)
        s.turn_player = s.first_player
        return cls((deck_a, deck_b), s, mode, [], auto_trivial, hash_log, invariants)

    def clone(self):
        """A copy that shares nothing mutable with this one.

        The decks are shared on purpose: a `Deck` is the decklist as declared
        and nothing in a game ever writes to it.
        """
        g = Game.__new__(Game)
        g.decks = self.decks
        g.mode = self.mode
        g.s = self.s.clone()
        g.log = self.log[:]
        g.auto_trivial = self.auto_trivial
        g.hash_log = self.hash_log
        g.check_invariants = self.check_invariants
        g.decisions = self.decisions
        return g

    # -- randomness ------------------------------------------------------

    def shuffle(self, seat, items):
        return rng.shuffle(self.s.seat_rng[seat], items)

    def choose(self, seat, options):
        state, i = rng.below(self.s.seat_rng[seat], len(options))
        return state, options[i]

    # -- the record ------------------------------------------------------

    def note(self, message, seat=None, private_to=None, detail=""):
        """Record a physical operation.

        `private_to` marks an entry as visible only to that seat — a draw names
        cards, and 108.7.c makes a hand Private Information. The entry is still
        recorded in full so a finished game can be reviewed; `detail` is the
        part a seat view redacts.
        """
        entry = {"turn": self.s.turn, "phase": self.s.phase, "text": message}
        if seat is not None:
            entry["seat"] = seat
        if private_to is not None:
            entry["private_to"] = private_to
            entry["detail"] = detail
        if self.hash_log:
            entry["h"] = self.s.hash()
        self.log.append(entry)
        return message

    def public_log(self, seat=None):
        """The log as `seat` may read it — another seat's draws stay hidden."""
        out = []
        for entry in self.log:
            item = dict(entry)
            if item.get("private_to") is not None and item["private_to"] != seat:
                item.pop("detail", None)
            elif "detail" in item:
                item["text"] = "%s [%s]" % (item["text"], item["detail"])
            out.append(item)
        return out

    # -- cleanups (319) --------------------------------------------------

    def need_cleanup(self):
        """Make a Cleanup an Outstanding Task, once."""
        if ("cleanup", "") not in self.s.tasks:
            self.s.tasks.insert(0, ("cleanup", ""))

    def board_changed(self):
        """319.6: after any number of Game Objects enter or leave the Board."""
        self.need_cleanup()

    def status_changed(self):
        """319.1/319.7: a state transition, or a status change."""
        self.need_cleanup()

    # -- asking ----------------------------------------------------------

    def ask(self, seat, kind, options, prompt="", window=""):
        """Stop the rules here and record the question."""
        if not options:
            raise RulesError("a decision with no legal options is a kernel bug "
                             "(%s, seat %d)" % (kind, seat))
        self.s.pending = {
            "seat": seat, "kind": kind, "prompt": prompt, "window": window,
            "options": [(o.key, o.label) for o in options],
        }

    def _decision(self):
        p = self.s.pending
        self.decisions += 1
        return Decision(
            p["seat"], p["kind"],
            [Option(key, label) for key, label in p["options"]],
            view(self.s, p["seat"]),
            prompt=p["prompt"])

    # -- the loop --------------------------------------------------------

    def step(self):
        """Run the rules until a choice is needed, and return it."""
        s = self.s
        for _ in range(self.MAX_TICKS):
            if s.winner is not None:
                if s.phase != OVER:
                    s.phase = OVER
                    self.note("game over: %s" % s.end_reason)
                return terminal(view(s, 0))
            if s.pending is not None:
                if self.auto_trivial and len(s.pending["options"]) == 1:
                    self._apply(s.pending["options"][0][0])
                    continue
                return self._decision()
            self._tick()
        raise RulesError("the kernel ran %d operations without reaching a decision "
                         "— it is spinning" % self.MAX_TICKS)

    def answer(self, choice):
        """Take one of the options the current decision offered. Refuse the rest."""
        s = self.s
        if s.pending is None:
            raise RulesError("there is no decision waiting to be answered")
        decision = self._decision_view()
        option = decision.find(choice)
        if option is None:
            raise RulesError(
                "%r is not one of the legal options: %s"
                % (choice, ", ".join(repr(o.key) for o in decision.options)))
        self._apply(option.key)
        self._verify("answering %r" % (option.key,))
        return self

    def _decision_view(self):
        p = self.s.pending
        return Decision(p["seat"], p["kind"],
                        [Option(key, label) for key, label in p["options"]],
                        None, prompt=p["prompt"])

    def _tick(self):
        """One mandatory operation: HOT FEPR, then the turn (334, 335)."""
        s = self.s

        # H — Handle Outstanding Tasks. Nothing else proceeds while one is
        # outstanding (333), and a Task incurred partway through the FEPR
        # process pauses it (334.2.a), which is what makes this the first check
        # rather than a step of its own.
        if s.tasks:
            name, arg = s.tasks.pop(0)
            if name == "cleanup":
                s.cleanups += 1
                if s.cleanups > turn.MAX_CLEANUPS:
                    raise RulesError("cleanups are not settling (322)")
            else:
                s.cleanups = 0
            turn.run_task(self, name, arg)
            self._verify(name)
            return

        # FEPR — the Chain, one step at a time (336).
        if s.chain:
            chain.fepr_step(self)
            self._verify("a FEPR step")
            return

        # A Showdown is a window of its own; the player with Focus acts (347).
        if s.showdown is not None and not s.showdown["closed"]:
            chain.showdown_step(self)
            return

        # 335: nothing outstanding, nothing pending, no Showdown.
        if s.phase == SETUP:
            turn.setup(self)
            return
        if s.phase == MAIN:
            self._ask_main()
            return
        turn.next_phase(self)
        self._verify("a phase change")

    def _verify(self, what):
        if self.check_invariants:
            from . import invariants
            invariants.assert_ok(self, what)

    # -- the Main Phase (316.5) ------------------------------------------

    def _ask_main(self):
        """316.5.b: a Neutral Open State, and only the Turn Player may act."""
        s = self.s
        seat = s.turn_player
        options = []

        # Playing a card. The Chosen Champion is played from the Champion Zone,
        # where 112 put it and 133.4 calls it a Main Deck Card; 108.3.c ("cannot
        # be returned to this zone by normal means") is the rule that only makes
        # sense if it leaves by being played.
        for zone in ("hand", "champion"):
            for name in sorted(set(getattr(s, zone)[seat])):
                if turn.category(name) == "other":
                    continue
                ok, _why = actions.can_pay(self, seat, name)
                if ok:
                    options.append(Option(("play", zone, name),
                                          "play %s from %s" % (name, zone)))

        # The Standard Move (144). Offered per unit; the destination is the
        # second half of the grouped decision.
        for unit in sorted(s.units, key=lambda u: _id_number(u["id"])):
            if unit["ctrl"] != seat:
                continue
            if self._move_destinations(unit):
                options.append(Option(("move", unit["id"]),
                                      "standard move %s [%s]" % (unit["name"], unit["id"])))

        # 316.9: a player who has no more Discretionary Actions they wish to
        # execute must indicate they are ending their turn.
        options.append(Option(("end",), "end the turn (316.9)"))
        s.choosing = None
        self.ask(seat, "main", options,
                 prompt="seat %d's Main Phase, %s" % (seat, s.turn_state()))

    def _move_destinations(self, unit):
        s = self.s
        spots = [loc_base(unit["ctrl"])] + [loc_bf(b["i"]) for b in s.battlefields]
        # The unit's own location is not filtered out here on purpose. 144.4
        # already refuses it — base to base and battlefield to battlefield are
        # both illegal shapes — and a second filter in front of that one cannot
        # be watched to fail, so it would read as covered while covering nothing.
        return [d for d in spots if not actions.standard_move_legal(s, unit, d)]

    # -- applying an answer ----------------------------------------------

    def _apply(self, key):
        s = self.s
        pending = s.pending
        s.pending = None
        seat = pending["seat"]
        kind = pending["kind"]
        what = s.choosing["what"] if s.choosing else None

        if kind == "mulligan":
            self._apply_mulligan(seat, key)
        elif kind == "main":
            self._apply_main(seat, key)
        elif kind == "target" and what == "play_location":
            item = next(c for c in s.chain if c["id"] == s.choosing["item"])
            item["loc"] = key[1]
            s.choosing = None
        elif kind == "target" and what == "move_to":
            oid = s.choosing["unit"]
            s.choosing = None
            actions.standard_move(self, oid, key[1])
        elif kind == "target" and what == "open_showdown":
            combat = s.choosing["combat"]
            s.choosing = None
            turn.open_showdown(self, key[1], combat)
            self.need_cleanup()
        elif kind == "chain" and pending["window"] == "showdown":
            chain.pass_focus(self, seat)
        elif kind == "chain":
            chain.pass_priority(self, seat)
        else:
            raise RulesError("no handler for a %r decision answered with %r"
                             % (kind, key))

    def _apply_mulligan(self, seat, key):
        s = self.s
        aside = list(s.choosing["aside"])
        if key[0] == "aside":
            aside.append(key[1])
            s.choosing = {"what": "mulligan", "seat": seat, "aside": aside}
            turn.ask_mulligan(self)
            return
        s.choosing = None
        turn.finish_mulligan(self, seat, aside)

    def _apply_main(self, seat, key):
        s = self.s
        if key[0] == "play":
            chain.play_card(self, seat, key[2], key[1])
        elif key[0] == "move":
            unit = s.unit(key[1])
            s.choosing = {"what": "move_to", "unit": key[1]}
            from .state import where
            self.ask(seat, "target",
                     [Option(("to", d), "move %s to %s" % (unit["name"], where(s, d)))
                      for d in self._move_destinations(unit)],
                     prompt="where does %s move? (144.4)" % unit["name"])
        elif key[0] == "end":
            self.note("seat %d ends their Main Phase (316.9)" % seat, seat=seat)
            turn.enter_phase(self, ENDING)
        else:
            raise RulesError("no handler for main action %r" % (key,))

    # -- determinization -------------------------------------------------

    def apply_seed(self, seat, seed):
        """One full-information world consistent with everything `seat` has seen.

        Kept: `seat`'s own hand, every public zone (both trashes, both banished
        piles, the board, the Champion Zones, points, runes), and the SIZE of
        every hidden zone. Redealt: the order of every deck, and which of the
        opponent's unseen cards are in their hand rather than in their deck.

        Two seeds give two different worlds, both consistent — that is the
        property a search needs, and `selftest` asserts both halves of it.
        """
        g = self.clone()
        s = g.s
        stream = rng.seed_from("%s/determinize/%s/%d" % (self.s.seed, seed, seat))
        other = 1 - seat

        # My own decks: I know what is in them, never the order.
        stream = rng.shuffle(stream, s.main_deck[seat])
        stream = rng.shuffle(stream, s.rune_deck[seat])
        # The opponent's Rune Deck is the decklist minus the runes on the board,
        # so its CONTENTS are public and only its order is hidden.
        stream = rng.shuffle(stream, s.rune_deck[other])

        # The opponent's hand and Main Deck are one unseen pool, partitioned by
        # a number I can see: how many cards they are holding.
        pool = self._unseen(other)
        holding = len(s.hand[other])
        if len(pool) != holding + len(s.main_deck[other]):
            raise RulesError(
                "determinization lost cards: %d unseen, %d in hand + %d in deck"
                % (len(pool), holding, len(s.main_deck[other])))
        stream = rng.shuffle(stream, pool)
        s.hand[other] = pool[:holding]
        s.main_deck[other] = pool[holding:]
        g.note("determinized for seat %d with seed %s — seat %d's %d hidden cards "
               "were redealt" % (seat, seed, other, len(pool)))
        return g

    def _unseen(self, seat):
        """Every Main Deck card of `seat`'s that is not in a zone anyone can see."""
        s = self.s
        deck = self.decks[seat]
        pool = list(deck.main_cards())
        if deck.chosen_champion:
            pool.append(deck.chosen_champion)
        for name in (s.trash[seat] + s.banished[seat] + s.champion[seat]
                     + [u["name"] for u in s.units if u["owner"] == seat]
                     + [c["name"] for c in s.chain if c["ctrl"] == seat]):
            if name in pool:
                pool.remove(name)
        return pool

    # -- reporting -------------------------------------------------------

    def state_hash(self):
        return self.s.hash()

    def view(self, seat):
        return view(self.s, seat)

    def winner(self):
        return self.s.winner

    def summary(self):
        s = self.s
        return {
            "seed": s.seed,
            "first_player": s.first_player,
            "turns": s.turn,
            "winner": s.winner,
            "end_reason": s.end_reason,
            "points": list(s.points),
            "decisions": self.decisions,
            "log_entries": len(self.log),
            "state_hash": s.hash(),
        }
