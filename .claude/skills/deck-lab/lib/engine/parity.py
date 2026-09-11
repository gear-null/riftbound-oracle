"""Differential testing against `table.py` — the same game, played twice.

The table (ADR 0007) holds a game while a person plays it; the engine (ADR 0009)
plays it. They are two independent implementations of the same rules, and that
makes the older one an oracle for the newer one on the subset both model. A
kernel that agrees with a thousand of its own games agrees with its own bugs;
agreeing with a second implementation is evidence of a different kind.

**The shape.** A scenario is a deck pair, a seed and an ANSWER FOR EVERY
DECISION — the same scripted sequence the goldens use. The engine is driven by
that script; each decision is translated into the table's own verbs through
`TO_TABLE` below; and after every step the two states are diffed on zones, unit
Might and position, battlefield control and Contested, and points. The first
mismatch is reported with the rule that decides it.

**Where they are compared.** At every Main Phase decision, and at the end. Those
are the moments the table can be in: it has no Chain, no Focus and no Steps of
Combat, so between "play this card" and "it is on the board" the engine passes
through states the table has no way to be in. Comparing there would be comparing
the engine against a tool that does not model the thing being compared.

**What cannot be mapped, and why**, is listed in `UNMAPPED` and repeated in
`docs/engine/testing.md`. **Where the two legitimately disagree** is `DIVERGENCES`,
by name, from `docs/engine/spec.md` — a harness that does not know its own
expected differences reports them as failures and gets muted.
"""
import table

from . import combat as combat_rules
from . import fixtures, policies, turn as turn_rules
from .game import Game
from .state import loc_base, loc_bf

#: Deliberate differences, named in docs/engine/spec.md. The harness knows each
#: one and says how it is handled, because a difference nobody named is a
#: difference somebody will silence the whole harness over.
DIVERGENCES = {
    "a unit enters the board exhausted (359.2.c)":
        "neutralised — the harness passes exhausted=True to the table's "
        "put_into_play, which defaults to ready and leaves it to its reader",
    "battlefields are placed in turn order (485.5)":
        "neutralised — the table's battlefields are transplanted from the "
        "engine's, so both index them the same way",
    "every loop over both players goes in turn order (303.2.a)":
        "invisible to a state diff — it changes the order events happen in, "
        "not the state they leave behind, and the mirror test is what pins it",
    "victory is decided at a cleanup, not inside the Score (472, 323.1)":
        "compared only at the end of the scenario — mid-game the table has "
        "already set a winner that the engine will only notice at the next "
        "Cleanup, and both agree once the game is actually over",
}

#: Table verbs with no engine option to map, and engine decisions with no table
#: verb. Both halves, because the harness covers the intersection and the reader
#: needs to know what is outside it.
UNMAPPED = {
    "chain (338.1) — the Execute window":
        "the table has no Chain: it applies a card's effect when its reader "
        "says so. There is nothing to pass priority in.",
    "chain (347) — the Showdown Focus window":
        "the table has no Focus and no Showdown State; its `cleanup` settles "
        "control directly.",
    "target — which staged Showdown or Combat opens (323.12, 323.13)":
        "the table never opens one; the reader calls `resolve_combat` at the "
        "battlefield they mean.",
    "table.combat_preview":
        "a reader's tool — it shows card text before damage is assigned. The "
        "engine assigns damage itself, so there is nothing to preview.",
    "table.set_target, banish, discard, recycle_card, attached Gear":
        "reachable only from card text, which this slice does not execute.",
}

SCENARIOS = [
    {"name": "irelia-vs-viktor-s7", "a": fixtures.IRELIA, "b": fixtures.VIKTOR,
     "seed": 7, "first": 0, "policy": "parity-7"},
    {"name": "viktor-vs-irelia-s7-swapped", "a": fixtures.VIKTOR, "b": fixtures.IRELIA,
     "seed": 7, "first": 1, "policy": "parity-7"},
    {"name": "viktor-vs-kennen-s23", "a": fixtures.VIKTOR, "b": fixtures.KENNEN,
     "seed": 23, "first": 0, "policy": "parity-23"},
]


def script(spec, limit=100000):
    """Every answer the engine is given, recorded as a list of option keys.

    Generated rather than hand-written, for the reason the goldens are: a
    hand-written script stops being a legal sequence the first time an option
    list changes, and then tests nothing. `auto_trivial=False` so the script
    holds an answer for the one-option decisions too — the `assign_damage`
    decisions with a single legal target are most of them.
    """
    game = _engine(spec)
    pol = policies.random_pair(spec["policy"])
    keys = []
    for _ in range(limit):
        decision = game.step()
        if decision.terminal:
            return keys
        option = pol[decision.seat](decision)
        keys.append(list(option.key))
        game.answer(option)
    raise AssertionError("%s never ended" % spec["name"])


def _engine(spec):
    return Game.new(fixtures.deck(spec["a"]), fixtures.deck(spec["b"]),
                    seed=spec["seed"], first=spec["first"],
                    hash_log=False, auto_trivial=False)


def run(spec, keys=None):
    """Play one scenario through both, and return the mismatches. Empty is right."""
    keys = keys if keys is not None else script(spec)
    game = _engine(spec)
    # Run the engine to its first question — 110-116 deal the game — and copy
    # the position it dealt onto the table. `step()` is idempotent once it is
    # holding a decision, so the loop below sees this same first decision.
    game.step()
    seat_decks = (fixtures.deck(spec["a"]), fixtures.deck(spec["b"]))
    top = table.Table(list(seat_decks), spec["seed"], first=spec["first"])
    top.setup()
    transplant(top, game.s)

    mirror = _Mirror(top)
    mirror.counter = game.s.next_id
    problems = []
    at = 0
    for _ in range(len(keys) + 2):
        decision = game.step()
        if decision.kind == "main" or decision.terminal:
            mirror.sync_turn(game)
            problems.extend("%s: %s" % (spec["name"], p) for p in mirror.problems)
            mirror.problems = []
            problems.extend(_diff(spec["name"], at, game, top, decision.terminal))
            if problems:
                return problems
        if decision.terminal:
            return problems
        if at >= len(keys):
            return ["%s: the engine asked decision %d and the script has %d answers"
                    % (spec["name"], at, len(keys))]
        key = tuple(keys[at])
        option = decision.find(key)
        if option is None:
            return ["%s: decision %d answers %r, which the engine did not offer: %s"
                    % (spec["name"], at, key, [o.key for o in decision.options])]
        at += 1
        mirror.before(game, decision, key)
        game.answer(option)
        mirror.after(game, decision, key)
        resync(top, game.s)
        mirror.counter = game.s.next_id
    return ["%s: the scenario did not finish in %d decisions"
            % (spec["name"], len(keys))]


# -- keeping the two games on the same deal ------------------------------

def transplant(top, s):
    """Give the table the engine's exact position, so both start from one deal.

    Two shuffles of the same decklist by two different generators are two
    different games, and a harness that began by comparing them would report
    every card as a mismatch. What is under test is the RULES, so the deal is
    taken from one side and the rules are then run on both.
    """
    for seat in (0, 1):
        p = top.players[seat]
        p.hand = list(s.hand[seat])
        p.main_deck = list(s.main_deck[seat])
        p.rune_deck = list(s.rune_deck[seat])
        p.trash = list(s.trash[seat])
        p.banished = list(s.banished[seat])
        p.champion_zone = list(s.champion[seat])
        p.points = s.points[seat]
        p.energy = s.energy[seat]
        p.power = dict(s.power[seat])
    top.battlefields = []
    for b in s.battlefields:
        bf = table.Battlefield(b["i"], b["name"], b["by"])
        bf.controller = b["ctrl"]
        bf.contested = b["contested"]
        bf.contested_by = b["contested_by"]
        bf.scored_by = set(b["scored"])
        top.battlefields.append(bf)
    top.permanents = []
    for u in s.units:
        perm = table.Permanent(u["id"], u["name"], u["ctrl"], u["loc"])
        perm.exhausted = u["exh"]
        perm.damage = u["dmg"]
        perm.buffs = u["buffs"]
        top.permanents.append(perm)
    top.runes = [table.Rune(r["id"], r["name"], r["ctrl"], r["exh"]) for r in s.runes]
    top.turn = s.turn
    top.turn_player = s.turn_player
    top.first_player = s.first_player
    top.second_player_channel_bonus_used = s.second_channel_used
    top.victory_target = s.victory_target
    top.winner = s.winner
    # The table runs a whole turn in one verb and the engine runs it as a
    # sequence of Tasks, so the harness starts the table between turns and lets
    # `_Mirror.sync_turn` begin each one as the engine reaches it.
    top.turn = 0
    top.phase = table.ENDING
    top.setup_done = True
    resync(top, s)


def resync(top, s):
    """Re-align the ORDER of the face-down decks, and nothing else.

    Both tools shuffle with their own generator, so a mulligan (117.3) or a burn
    out (431.2.b) leaves the same multiset of cards in a different order and the
    next draw takes a different card — a divergence with no rule behind it.

    Only when the two decks hold the SAME CARDS. Mid-play the engine and the
    table are a step apart — the engine pays a cost when the Chain finalizes and
    the table pays it when the card is played — and copying across that gap
    would overwrite a real difference with the engine's own answer, which is the
    one way a differential harness can be made to agree with anything.
    """
    for seat in (0, 1):
        player = top.players[seat]
        for zone, want in (("main_deck", s.main_deck[seat]),
                           ("rune_deck", s.rune_deck[seat])):
            mine = getattr(player, zone)
            if mine != want and sorted(mine) == sorted(want):
                setattr(player, zone, list(want))


# -- the mapping ---------------------------------------------------------

class _Mirror:
    """Applies to the table whatever the engine was just told to do.

    Stateful, because two of the engine's decisions are the two halves of one
    grouped choice (`decisions.py`, property 2) and the table's verb needs both:
    which card, then where it enters.
    """

    def __init__(self, top):
        self.t = top
        self.play = None
        self.move = None
        self.aside = {0: [], 1: []}
        self.assigning = None
        #: The engine's id counter as it stood before the engine's last `step`.
        #: Object ids are not a rule, but the harness compares them: two tools
        #: that mint the same ids can be diffed unit for unit instead of by a
        #: fuzzy match on name and position, and a move can name a unit. The
        #: engine burns one id per Chain item and the table has no Chain, so the
        #: counter is handed over at each point the table is about to mint.
        self.counter = 0
        #: Disagreements the diff cannot see, because they are about a choice
        #: rather than about a state. Collected here and reported alongside it.
        self.problems = []

    def sync_turn(self, game):
        """Bring the table up to the turn the engine has just started.

        Called at every comparison point rather than at the `end` answer: 315's
        Awaken, Scoring, Channel and Draw are four Tasks in the engine and one
        verb here, and the engine can stop on a decision partway through them.
        """
        self.t._next_id = self.counter
        while self.t.winner is None and self.t.turn < game.s.turn:
            self.t.begin_turn()

    def before(self, game, decision, key):
        """What must be read from the engine BEFORE the answer changes it."""
        if decision.kind == "assign_damage":
            c = game.s.choosing
            if self.assigning is None:
                self._compare_assignment(game, c)
            self.assigning = {"bf": c["bf"], "attacker": c["attacker"]}

    def _compare_assignment(self, game, c):
        """The two implementations' own lethal-first assignments, side by side.

        The state diff cannot see this one. The harness gives the table the
        damage the engine actually assigned, so that the RESOLUTION is what is
        compared — which means a wrong assignment would be copied across and
        agree with itself. 465.2.c is checked here instead, by asking each tool
        for its own answer on the same board and requiring the same dict.
        """
        s, index = game.s, c["bf"]
        mine = (combat_rules.attacking_units(s, index),
                combat_rules.defending_units(s, index))
        if c["by"] != c["attacker"]:
            mine = (mine[1], mine[0])
        location = loc_bf(index)
        theirs = (self.t.units_at(location, c["by"]),
                  self.t.units_at(location, 1 - c["by"]))
        engine_says = combat_rules.assign_damage(s, mine[0], mine[1])
        table_says = self.t.assign_damage(theirs[0], theirs[1])
        if engine_says != table_says:
            self.problems.append(
                "seat %d's lethal-first assignment at %s differs — 465.2.c\n"
                "      engine: %r\n      table:  %r"
                % (c["by"], s.battlefield(index)["name"],
                   engine_says, table_says))

    def after(self, game, decision, key):
        kind, seat = decision.kind, decision.seat
        if kind == "mulligan":
            if key[0] == "aside":
                self.aside[seat].append(key[1])
            else:
                self.t.mulligan(seat, self.aside[seat])
                self.aside[seat] = []
            return
        if kind == "main" and key[0] == "play":
            # 355.2 asks a UNIT where it enters and asks nothing of a Spell or a
            # non-Unit Gear, so only a unit has a second half to wait for.
            if turn_rules.category(key[2]) == "unit":
                self.play = (seat, key[1], key[2])
            else:
                self._played(game, seat, key[2], loc_base(seat))
            return
        if kind == "main" and key[0] == "move":
            self.move = (seat, key[1])
            return
        if kind == "main" and key[0] == "end":
            # 317: the Ending Phase and the handover. The NEXT turn is begun by
            # `sync_turn`, when the engine has finished beginning its own —
            # the engine spreads 315 over four Tasks and can stop at a decision
            # inside any of them.
            self.t.end_turn()
            return
        if kind == "target" and self.play is not None:
            seat, _zone, name = self.play
            self.play = None
            self._played(game, seat, name, key[1])
            return
        if kind == "target" and self.move is not None:
            seat, oid = self.move
            self.move = None
            self.t.standard_move(oid, key[1])
            self.t.cleanup()
            return
        if kind == "assign_damage":
            self._assigned(game, key)
            return
        # Everything else — the Chain window, the Showdown window, the choice of
        # which battlefield opens — has no table verb. `UNMAPPED` says why.

    def _played(self, game, seat, name, location):
        """356-359: pay, then let the card arrive where its category puts it."""
        # The engine mints the permanent when the Chain item resolves, a step
        # later, and `next_id` is already standing at the number it will use.
        self.t._next_id = game.s.next_id
        self.t.pay(seat, name)
        category = turn_rules.category(name)
        if category == "spell":
            # 351.2: the Spell's effects happen and the card goes to the trash.
            # Neither tool executes the text, so both do exactly the move.
            self.t.play_spell(seat, name)
        else:
            # 359.2.c: a Unit enters EXHAUSTED. The table's default is ready and
            # `docs/engine/spec.md` records that as divergence 1; 359.2.d puts a
            # non-Unit Gear at its controller's base, Ready.
            self.t.put_into_play(seat, name, location,
                                 exhausted=(category == "unit"))
        self.t.cleanup()

    def _assigned(self, game, key):
        """Feed the engine's own chosen assignment to the table's combat.

        `resolve_combat` takes both assignments explicitly, so the table runs
        the same damage the engine assigned rather than recomputing one — which
        is what makes this a comparison of the RESOLUTION rather than a second
        run of the same assignment code.
        """
        c = game.s.choosing
        state = self.assigning
        if c is not None and c.get("what") == "assign_damage":
            return                                   # more targets to come
        self.assigning = None
        if state is None:
            return
        attacker, index = state["attacker"], state["bf"]
        # The engine has dealt the damage by now, so the assignment is read back
        # off the board: every unit at the battlefield, and what is marked on it.
        onto = {"a": {}, "d": {}}
        for unit in self.t.units_at(loc_bf(index)):
            marked = _marked(game.s, unit.id)
            if marked:
                onto["d" if unit.controller == attacker else "a"][unit.id] = marked
        self.t.resolve_combat(index, attacker_assignment=onto["a"],
                              defender_assignment=onto["d"])


def _marked(s, oid):
    for unit in s.units:
        if unit["id"] == oid:
            return unit["dmg"]
    return 0


# -- the diff ------------------------------------------------------------

def snapshot(s, top):
    """The two states as the same shape, so a diff is a dict comparison."""
    engine = {
        "points": list(s.points),
        "battlefields": [(b["name"], b["ctrl"], b["contested"], b["contested_by"],
                          sorted(b["scored"])) for b in s.battlefields],
        "units": sorted((u["id"], u["name"], u["ctrl"], u["loc"], u["exh"],
                         u["dmg"], s.might_of(u)) for u in s.units),
        "runes": sorted((r["id"], r["name"], r["ctrl"], r["exh"]) for r in s.runes),
    }
    for seat in (0, 1):
        engine["zones%d" % seat] = [
            sorted(s.hand[seat]), sorted(s.main_deck[seat]), sorted(s.rune_deck[seat]),
            sorted(s.trash[seat]), sorted(s.banished[seat]), sorted(s.champion[seat])]
    mirror = {
        "points": [p.points for p in top.players],
        "battlefields": [(b.name, b.controller, b.contested, b.contested_by,
                          sorted(b.scored_by)) for b in top.battlefields],
        "units": sorted((u.id, u.name, u.controller, u.location, u.exhausted,
                         u.damage, u.might) for u in top.permanents),
        "runes": sorted((r.id, r.name, r.controller, r.exhausted) for r in top.runes),
    }
    for seat in (0, 1):
        p = top.players[seat]
        mirror["zones%d" % seat] = [
            sorted(p.hand), sorted(p.main_deck), sorted(p.rune_deck),
            sorted(p.trash), sorted(p.banished), sorted(p.champion_zone)]
    return engine, mirror


#: Which rule decides each field, so a mismatch reports one instead of a diff.
RULE_FOR = {
    "points": "467-472 scoring, and 431.2.c",
    "battlefields": "188-192 control, 190.3.a Contested, 470 once per turn",
    "units": "465 combat damage, 428 kill, 144/446 movement, 359.2 entering",
    "runes": "430 channel, 164.2 paying",
    "zones0": "413 draw, 416 recycle, 428 trash, 431 burn out",
    "zones1": "413 draw, 416 recycle, 428 trash, 431 burn out",
}


def _diff(name, at, game, top, final):
    engine, mirror = snapshot(game.s, top)
    out = []
    for field in sorted(engine):
        if engine[field] != mirror[field]:
            out.append("%s: after decision %d the two disagree on %s — %s\n"
                       "      engine: %r\n      table:  %r"
                       % (name, at, field, RULE_FOR.get(field, "?"),
                          engine[field], mirror[field]))
    if final and game.s.winner != top.winner:
        # Divergence 4 is about WHEN the win is noticed, never about who won.
        out.append("%s: the game ended with different winners — engine %r, table %r "
                   "(472)" % (name, game.s.winner, top.winner))
    return out


def run_all():
    """Every scenario. Returns the problems, and how many steps were compared."""
    problems, compared = [], 0
    for spec in SCENARIOS:
        keys = script(spec)
        compared += len(keys)
        problems.extend(run(spec, keys))
    return problems, compared
