"""The ability framework's regression checks (360-406, 367-375, 473-480).

Three sections, run by `engine/selftest.py` as part of the one suite, with the
same discipline as the rest of it: every check names the rule it pins, and every
check has a mutant in `../mutants.py` that reintroduces the defect it is named
for. A check nobody has watched fail is not yet a check.

The abilities here are **hand-built** — no card text is parsed in this slice —
and the registry they go into is module-global card data. So every section
clears it on the way in AND on the way out: a fixture left attached changes
every game that runs after it, which is how a perft golden moves for a reason
nobody can name.
"""
import os
import re

from . import (abilities, actions, demo, fixtures, layers, policies,
               replacements, turn)
from .abilities import Ability, Cost, Gate, Trigger
from .decisions import EMITTED
from .game import Game
from .state import loc_base, loc_bf

HERE = os.path.dirname(os.path.abspath(__file__))

#: Real gauntlet cards, so `new_unit` can look up a Might and a type. Named here
#: rather than inline for the reason `fixtures.ALL` is: the day one is renamed,
#: the failure should be one sentence and not a KeyError six frames down.
CRAB = "Scuttle Crab"            # Might 0
TIDE = "Tideturner"              # Might 2
HERDER = "Stellacorn Herder"     # Might 3
PYKE = "Pyke - Returned"         # Might 3
DREDGER = "Carrion Dredger"      # Might 1
SHARP = "Card Sharp"             # Might 3
AKALI = "Akali, Silent"          # Might 4
BROKER = "Honest Broker"         # Might 2

#: Every decision kind these sections actually saw emitted. `EMITTED` is a
#: claim; this is the evidence, and the last check compares the two.
SEEN = set()


# -- fixtures ------------------------------------------------------------

def _h():
    """The suite's shared fixtures. Imported late: `selftest` imports US."""
    from . import selftest
    return selftest


def board(units=(), seed=7, first=0):
    """A game stopped in the Turn Player's Main Phase, with units placed.

    The units are dropped straight onto the board, which skips the play process
    on purpose: most of what this file probes is a board shape a vanilla game
    reaches rarely, and waiting for one is not a test.
    """
    st = _h()
    g = st.at_main(seed=seed, first=first)
    made = [st.put(g, seat, name, loc) for seat, name, loc in units]
    st.refresh(g)
    layers.recompute(g)
    return g, made


def drive(g, prefer=(), limit=200):
    """Step until the next Main Phase decision, preferring named option keys.

    `prefer` is a tuple of first-elements: the driver takes the first option
    whose key starts with one of them, and option 0 otherwise. That is how a
    check says "decline this one" without depending on where in the list the
    engine happened to put it.
    """
    for _ in range(limit):
        d = g.step()
        if d.terminal or d.kind == "main":
            return d
        SEEN.add(d.kind)
        pick = None
        for want in prefer:
            pick = next((o for o in d.options if o.key[0] == want), None)
            if pick is not None:
                break
        g.answer(pick if pick is not None else d.options[0])
    raise AssertionError("the game did not reach a Main Phase in %d steps" % limit)


def survives(fn):
    """Run `fn` and say whether the kernel stayed on its feet.

    A check whose subject is "the engine refuses X rather than doing X" has to
    survive the mutant that makes it do X — otherwise the suite dies, the battery
    records a CRASH instead of a named check, and the check keeps a credit nobody
    earned.
    """
    from .state import RulesError
    try:
        fn()
    except RulesError:
        return False
    return True


def settle(g, prefer=()):
    """Throw away the question the engine is holding, then drive on.

    `step()` returns the PENDING decision before it runs anything, so a second
    `drive` after a first one returns the same Main Phase decision instantly and
    the rules in between never run. That is how "a once each turn ability does
    not trigger twice" passed while triggering exactly once for the wrong reason.
    """
    _h().refresh(g)
    return drive(g, prefer)


def xp_effect(n=1):
    def effect(g, ctx):
        actions.gain_xp(g, ctx["seat"], n)
    return effect


def might_mod(n, oid=None):
    def modifier(g, src):
        return [{"op": "give_might", "n": n, "targets": (oid or src["oid"],)}]
    return modifier


def run_triggers(g):
    """Put whatever has triggered onto the Chain, without playing a whole game."""
    abilities.put_triggers_on_chain(g)
    if g.s.pending is not None:
        SEEN.add(g.s.pending["kind"])
    return g.s.chain


def kernel_modules():
    """The engine's own modules - the suite's own files are not the kernel.

    Both scans below ask what the RULES raise, and a test that constructs an
    event in order to prove it is refused is not a rule raising one. Counting
    this file would have the suite answer its own question.
    """
    return [n for n in sorted(os.listdir(HERE))
            if n.endswith(".py") and not n.startswith("selftest")]


def a_spell(deck):
    import cards
    for name in sorted(set(deck.main_cards())):
        if cards.card_type(name) == cards.SPELL:
            return name
    raise AssertionError("no spell in the fixture deck")


# =======================================================================
# abilities
# =======================================================================

def engine_abilities(check):
    abilities.clear()
    try:
        _kinds(check)
        _presence(check)
        _gates(check)
        _activated(check)
        _triggered(check)
        _ordering(check)
        _created(check)
        _events(check)
    finally:
        abilities.clear()


def _kinds(check):
    abilities.clear()
    abilities.register(TIDE, Ability("passive", text="+2 Might",
                                     modifier=might_mod(2)))
    g, (unit,) = board([(0, TIDE, loc_base(0))])
    check("a Passive Ability applies while its source is on the Board (363, 365.1)",
          g.s.might_of(unit) == unit["might"] + 2,
          "Might %d, printed %d" % (g.s.might_of(unit), unit["might"]))

    check("an ability kind the rules do not list is refused (361.1)",
          _h().raises(lambda: Ability("hexproof"), "not an ability kind"))
    check("a zone an ability cannot function in is refused (365-366)",
          _h().raises(lambda: Ability("passive", presence=("sideboard",)),
                      "not a zone"))
    check("a Triggered Ability without a Condition is refused (383.2)",
          _h().raises(lambda: Ability("triggered"), "has a condition"))
    check("a trigger event outside the census's vocabulary is refused (383)",
          _h().raises(lambda: Trigger(("when_i_feel_like_it",)), "not a trigger event"))

    # 396: "Linked Abilities can contain component Abilities of any type", so
    # being linked cannot be a seventh kind that the other six then are not.
    check("`linked` is a relation over a set, not an ability kind (394, 396)",
          "linked" not in abilities.KINDS
          and "link" in Ability("passive").__slots__)
    abilities.clear()
    check("a link name with one component is refused — a Linked set is a SET (394)",
          _h().raises(lambda: abilities.register(
              TIDE, Ability("passive", link="solo", modifier=might_mod(1))),
              "one component"))
    abilities.clear()


def _presence(check):
    abilities.clear()
    g, (target,) = board([(0, TIDE, loc_base(0))])
    printed = target["might"]
    g.s.hand[0].append(PYKE)

    abilities.register(PYKE, Ability("passive", text="board only",
                                     presence=("board",),
                                     modifier=might_mod(2, target["id"])))
    layers.recompute(g)
    check("a Passive Ability of a permanent does not apply from a hand (365.1)",
          g.s.might_of(target) == printed, "Might %d" % g.s.might_of(target))

    abilities.clear()
    abilities.register(PYKE, Ability("passive", text="from anywhere",
                                     presence=("hand",),
                                     modifier=might_mod(2, target["id"])))
    layers.recompute(g)
    check("an ability whose presence names a zone applies from that zone "
          "(366.1)",
          g.s.might_of(target) == printed + 2, "Might %d" % g.s.might_of(target))

    g.s.hand[0].remove(PYKE)
    layers.recompute(g)
    check("and stops the moment the card leaves that zone (366.1, 370.3)",
          g.s.might_of(target) == printed)

    # 366.2.a: a passive that alters costs applies "at all times in any zone
    # from which the card with the ability can be played".
    abilities.clear()
    spell = a_spell(g.decks[0])
    g.s.hand[0].append(SHARP)
    full = actions.cost_of(spell)["energy"]
    abilities.register(SHARP, Ability(
        "cost_replacement", text="your spells cost 1 less", presence=("hand",),
        applies=lambda gg, ev, src: ev.get("seat") == src["seat"]
        and turn.category(ev.get("name", "")) == "spell",
        replace=lambda gg, ev, src: ("energy", -1)))
    check("a cost-altering passive applies from the zone the card is played "
          "from (366.2.a)",
          actions.total_cost(g, 0, spell)["energy"] == max(full - 1, 0),
          "%d -> %d" % (full, actions.total_cost(g, 0, spell)["energy"]))
    abilities.clear()


def _gates(check):
    abilities.clear()
    check("only a Dependent Keyword can gate an ability (727.1, 135.2.e.7.b)",
          _h().raises(lambda: Gate("Tank"), "not a dependent keyword"))

    abilities.register(TIDE, Ability("passive", text="[Level 3] +2 Might",
                                     gate=Gate("Level", 3), modifier=might_mod(2)))
    g, (unit,) = board([(0, TIDE, loc_base(0))])
    printed = unit["might"]
    check("a [Level N] ability is Inactive below N XP (824.1.c, 721.2)",
          g.s.might_of(unit) == printed, "Might %d at %d XP" % (g.s.might_of(unit),
                                                                g.s.xp[0]))
    actions.gain_xp(g, 0, 3)
    check("and becomes Active the moment the controller reaches N XP (824.1.c)",
          g.s.might_of(unit) == printed + 2)
    actions.spend_xp(g, 0, 1)
    check("and Inactive again as soon as they have less than N — mid-turn, not "
          "at the next cleanup (824.1.d)",
          g.s.might_of(unit) == printed,
          "Might %d at %d XP" % (g.s.might_of(unit), g.s.xp[0]))

    # 812.1.c: a card DIFFERENT from the one with Legion, finalized this turn.
    abilities.clear()
    abilities.register(TIDE, Ability("passive", text="[Legion] +2 Might",
                                     gate=Gate("Legion"), modifier=might_mod(2)))
    g, (unit,) = board([(0, TIDE, loc_base(0))])
    printed = unit["might"]
    check("a [Legion] ability is Inactive before anything has been finalized "
          "(812.1.c)", g.s.might_of(unit) == printed)
    g.s.played[0] = [TIDE]
    layers.recompute(g)
    check("and its own play does not satisfy it — 812.1.c wants a DIFFERENT card",
          g.s.might_of(unit) == printed)
    g.s.played[0] = [TIDE, CRAB]
    layers.recompute(g)
    check("a second card finalized this turn satisfies [Legion] (812.1.c)",
          g.s.might_of(unit) == printed + 2)
    turn.begin_turn(g)
    check("and the new turn closes it again, because the record is per turn "
          "(812.1.c)", g.s.might_of(unit) == printed)

    # 828.1.c: while the Game Object has the Empowered status.
    abilities.clear()
    abilities.register(TIDE, Ability("passive", text="[Empowered] +2 Might",
                                     gate=Gate("Empowered"), modifier=might_mod(2)))
    g, (unit,) = board([(0, TIDE, loc_base(0))])
    printed = unit["might"]
    before = g.s.might_of(unit)
    actions.empower(g, unit["id"])
    check("an [Empowered] ability turns on with the status it names (828.1.c, 441)",
          before == printed and g.s.might_of(unit) == printed + 2)

    # 721.2 / 727.1.c.1: an Inactive trigger is not even evaluated.
    abilities.clear()
    abilities.register(PYKE, Ability(
        "triggered", text="when I die, gain 1 XP",
        gate=Gate("Level", 4), trigger=Trigger(("die",), who="me"),
        effect=xp_effect()))
    g, (unit,) = board([(0, PYKE, loc_base(0))])
    actions.to_trash(g, unit["id"])
    check("an Inactive Triggered Ability does not trigger (721.2, 727.1.c.1)",
          not g.s.trigs, "%d trigger(s) queued" % len(g.s.trigs))
    g, (unit,) = board([(0, PYKE, loc_base(0))])
    actions.gain_xp(g, 0, 4)
    actions.to_trash(g, unit["id"])
    check("and the same ability triggers once its keyword's condition is met "
          "(727.1.b.2)", len(g.s.trigs) == 1)

    # 722.1: Inactive text is still present on the card.
    g, (unit,) = board([(0, PYKE, loc_base(0))])
    listed = abilities.describe(g, unit)
    check("a card with Inactive text still HAS the ability, for anything that "
          "asks (722.1, 727.1.b.1)",
          len(listed) == 1 and "INACTIVE" in listed[0] and "[Level 4]" in listed[0],
          listed[0] if listed else "nothing listed")
    abilities.clear()


def _activated(check):
    abilities.clear()
    abilities.register(HERDER, Ability("activated", text="[E]: gain 1 XP",
                                       cost=Cost(exhaust_self=True),
                                       effect=xp_effect()))
    # BOTH seats have one. Without the opponent's copy the second check below
    # passes for the wrong reason — there is nothing of theirs to offer — and a
    # kernel that ignored 381 entirely would still look right.
    g, (unit, theirs) = board([(0, HERDER, loc_base(0)), (1, HERDER, loc_base(1))])
    offered = [src for src in abilities.activatable(g, 0)]
    check("an Activated Ability is offered to its controller in a Neutral Open "
          "State (377, 381)",
          len(offered) == 1 and offered[0]["oid"] == unit["id"])
    check("and not to the other seat, whose turn it is not (381)",
          not abilities.activatable(g, 1),
          "seat 1 controls %s and it is seat %d's turn"
          % (theirs["name"], g.s.turn_player))

    unit["exh"] = True
    check("an Activated Ability whose cost cannot be paid is not offered "
          "(402.3, 203.3)", not abilities.activatable(g, 0))
    unit["exh"] = False

    d = g.step()
    use = next((o for o in d.options if o.key[0] == "use"), None)
    check("the Main Phase decision carries it as a `use` option (378)",
          use is not None and use.key[1] == unit["id"])
    g.answer(use)
    item = g.s.chain[-1]
    check("activating puts a Pending Item on the Chain with no card behind it "
          "(377.3.a, 401.1)",
          item["kind"] == "ability" and item["pending"] and item["name"] == HERDER)
    check("and that Closes the State (401.1, 309.1)",
          g.s.turn_state().endswith("closed"))
    check("the cost is not paid until finalization (403, 404)", not unit["exh"])
    drive(g)
    check("the ability resolves and its effect happens (406.5)", g.s.xp[0] == 1)
    check("and its cost was paid on the way (404.1)",
          g.s.unit(unit["id"])["exh"])

    # 400.2 / 429.2.a: an Add ability resolves the moment it is finalized, and
    # Priority does not pass. Measured by the windows the Chain opened.
    abilities.clear()
    abilities.register(HERDER, Ability("activated", text="[E]: Add 1 XP",
                                       cost=Cost(exhaust_self=True),
                                       effect=xp_effect(), adds=True))
    g, (unit,) = board([(0, HERDER, loc_base(0))])
    g.auto_trivial = False
    d = g.step()
    g.answer(next(o for o in d.options if o.key[0] == "use"))
    adds_windows = _count_chain_windows(g)
    abilities.clear()
    abilities.register(HERDER, Ability("activated", text="[E]: gain 1 XP",
                                       cost=Cost(exhaust_self=True),
                                       effect=xp_effect()))
    g2, (unit2,) = board([(0, HERDER, loc_base(0))])
    g2.auto_trivial = False
    d2 = g2.step()
    g2.answer(next(o for o in d2.options if o.key[0] == "use"))
    plain_windows = _count_chain_windows(g2)
    check("an Add ability resolves as soon as it is finalized, without passing "
          "Priority (400.2, 429.2.a)",
          adds_windows == 0 and plain_windows > 0,
          "Add opened %d window(s), an ordinary ability %d"
          % (adds_windows, plain_windows))
    abilities.clear()


def _count_chain_windows(g):
    windows = 0
    for _ in range(60):
        d = g.step()
        if d.terminal or d.kind == "main":
            break
        if d.kind == "chain":
            windows += 1
        SEEN.add(d.kind)
        g.answer(d.options[0])
    return windows


def _triggered(check):
    abilities.clear()
    st = _h()

    # 383.4.a.2: a Play Effect goes on the Chain after the permanent enters.
    g, d = st.with_playable("unit", seed=13, auto_trivial=False)
    name = next(o.key[2] for o in d.options
                if o.key[0] == "play" and turn.category(o.key[2]) == "unit")
    seat = d.seat
    abilities.register(name, Ability(
        "triggered", text="when you play me, gain 1 XP", cite="CR:383.4.a",
        trigger=Trigger(("play_self",), who="me"), effect=xp_effect()))
    g.answer(next(o for o in d.options if o.key[0] == "play" and o.key[2] == name))
    drive(g)
    check("a Play Effect triggers after the permanent enters the Board "
          "(383.4.a.2)", g.s.xp[seat] == 1,
          "%s: XP %r" % (name, g.s.xp))
    check("and the log names the rule it triggered under (383.3)",
          any("triggers" in e["text"] and "383.3" in e["text"] for e in g.log))

    # 383.3.a: "you may" as the FIRST part of the effect, decided at
    # finalization, and 402.1.a removes it from the Chain if declined.
    abilities.clear()
    abilities.register(name, Ability(
        "triggered", text="when you play me, you MAY gain 1 XP", optional=True,
        trigger=Trigger(("play_self",), who="me"), effect=xp_effect()))
    g, d = st.with_playable("unit", seed=13, auto_trivial=False)
    g.answer(next(o for o in d.options if o.key[0] == "play" and o.key[2] == name))
    kinds = _kinds_asked(g, prefer=("skip",))
    check("a \"you may\" Triggered Ability asks an `optional` decision during "
          "finalization (383.3.a, 402.1)", "optional" in kinds,
          ", ".join(sorted(kinds)))
    check("declining removes it from the Chain and it counts as not having "
          "triggered (383.3.a.2, 402.1.a)",
          g.s.xp[seat] == 0 and not g.s.chain,
          "XP %r, chain %d" % (g.s.xp, len(g.s.chain)))
    g, d = st.with_playable("unit", seed=13, auto_trivial=False)
    g.answer(next(o for o in d.options if o.key[0] == "play" and o.key[2] == name))
    drive(g, prefer=("do",))
    check("and accepting performs it (383.3.a.1)", g.s.xp[seat] == 1)

    # 404.2: a player may decline to pay for a Triggered Ability that incurred
    # a cost, and it then leaves the Chain without being countered.
    abilities.clear()
    abilities.register(PYKE, Ability(
        "triggered", text="when I die, pay 1 XP: gain 2 XP",
        cost=Cost(xp=1), trigger=Trigger(("die",), who="me"),
        effect=xp_effect(2)))
    g, (unit,) = board([(0, PYKE, loc_base(0))])
    actions.gain_xp(g, 0, 1)
    actions.to_trash(g, unit["id"])
    g.auto_trivial = False
    kinds = _kinds_asked(g, prefer=("decline",))
    check("a Triggered Ability with a cost asks a `cost` decision at "
          "finalization (404.2)", "cost" in kinds, ", ".join(sorted(kinds)))
    check("declining to pay removes it from the Chain, and that is not being "
          "countered (404.2, 404.2.a)",
          g.s.xp[0] == 1 and not g.s.chain,
          "XP %r, chain %d" % (g.s.xp, len(g.s.chain)))
    check("and the log says so rather than reporting a counter (404.2.a)",
          any("not being countered" in e["text"] for e in g.log))
    g, (unit,) = board([(0, PYKE, loc_base(0))])
    actions.gain_xp(g, 0, 1)
    actions.to_trash(g, unit["id"])
    drive(g, prefer=("pay",))
    check("paying performs it (404.1, 203)", g.s.xp[0] == 2, "XP %r" % (g.s.xp,))

    # 203.3: a cost that is impossible cannot be paid, so the ability goes. Run
    # through `survives`, because the defect this names is "pay it anyway", and
    # paying 1 XP out of 0 raises — which would take the suite down with it.
    g, (unit,) = board([(0, PYKE, loc_base(0))])
    actions.to_trash(g, unit["id"])
    stood = survives(lambda: drive(g))
    check("a Triggered Ability whose cost is impossible leaves the Chain "
          "without being asked about (403, 404.2, 203.3)",
          stood and g.s.xp[0] == 0 and not g.s.chain,
          "the kernel tried to pay a cost it had already been told was "
          "impossible" if not stood else "")

    # 383.2.c.1 / 808: the object that died is not on the Board any more.
    abilities.clear()
    abilities.register(PYKE, Ability(
        "triggered", text="[Deathknell] gain 1 XP", cite="CR:808",
        trigger=Trigger(("die",), who="me"), effect=xp_effect()))
    g, (unit,) = board([(0, PYKE, loc_base(0))])
    actions.to_trash(g, unit["id"])
    check("a die trigger fires from an object that has already left the Board "
          "(383.2.c.1, 808)", len(g.s.trigs) == 1,
          "%d queued" % len(g.s.trigs))

    # 383.4.c.2 / 383.4.d.2: `who` is what tells "when I" from "when you".
    abilities.clear()
    abilities.register(TIDE, Ability(
        "triggered", text="when I am readied", trigger=Trigger(("readied",), who="me"),
        effect=xp_effect()))
    # The other unit is a DIFFERENT card on purpose: two copies of the same one
    # both carry the ability, and "another object" would then be another object
    # that is also listening.
    g, (mine, other) = board([(0, TIDE, loc_base(0)), (0, CRAB, loc_base(0))])
    other["exh"] = True
    actions.ready(g, other["id"])
    check("a `me` listener ignores the same event on another object (383.4.c.2)",
          not g.s.trigs, "%d queued" % len(g.s.trigs))
    mine["exh"] = True
    actions.ready(g, mine["id"])
    check("and fires for its own (383.4.a.1, 383.4.c.1)", len(g.s.trigs) == 1)

    abilities.clear()
    abilities.register(TIDE, Ability(
        "triggered", text="when an enemy unit is readied",
        trigger=Trigger(("readied",), who="enemy"), effect=xp_effect()))
    g, (mine, theirs) = board([(0, TIDE, loc_base(0)), (1, CRAB, loc_base(1))])
    theirs["exh"] = True
    actions.ready(g, theirs["id"])
    check("an `enemy` listener fires on the opposing seat's event (383.4.c.2)",
          len(g.s.trigs) == 1)

    # 383.3.e.1 / 383.1.b: frequency.
    abilities.clear()
    abilities.register(TIDE, Ability(
        "triggered", text="once each turn, when I am readied, gain 1 XP",
        trigger=Trigger(("readied",), who="me", frequency=("limit", 1, "turn")),
        effect=xp_effect()))
    g, (unit,) = board([(0, TIDE, loc_base(0))])
    unit["exh"] = True
    actions.ready(g, unit["id"])
    settle(g)
    first = g.s.xp[0]
    g.s.unit(unit["id"])["exh"] = True
    actions.ready(g, unit["id"])
    queued = len(g.s.trigs)
    settle(g)
    check("a \"once each turn\" Triggered Ability does not trigger again once it "
          "has been performed (383.3.e.1)",
          first == 1 and queued == 0 and g.s.xp[0] == 1,
          "XP %r, %d queued the second time" % (g.s.xp, queued))

    abilities.clear()
    abilities.register(TIDE, Ability(
        "triggered", text="the 2nd time I am readied each turn, gain 1 XP",
        trigger=Trigger(("readied",), who="me", frequency=("nth", 2, "turn")),
        effect=xp_effect()))
    g, (unit,) = board([(0, TIDE, loc_base(0))])
    unit["exh"] = True
    actions.ready(g, unit["id"])
    once = len(g.s.trigs)
    unit["exh"] = True
    actions.ready(g, unit["id"])
    check("\"the Nth time\" triggers on the Nth and not before (383.1.b)",
          once == 0 and len(g.s.trigs) == 1,
          "after one: %d, after two: %d" % (once, len(g.s.trigs)))
    abilities.clear()


def _kinds_asked(g, prefer=(), limit=60):
    kinds = set()
    for _ in range(limit):
        d = g.step()
        if d.terminal or d.kind == "main":
            break
        kinds.add(d.kind)
        SEEN.add(d.kind)
        pick = None
        for want in prefer:
            pick = next((o for o in d.options if o.key[0] == want), None)
            if pick is not None:
                break
        g.answer(pick if pick is not None else d.options[0])
    return kinds


def _ordering(check):
    abilities.clear()
    abilities.register(TIDE, Ability(
        "triggered", text="when a unit is readied, gain 1 XP",
        trigger=Trigger(("readied",), who="any"), effect=xp_effect()))
    g, (one, two, spare) = board([(0, TIDE, loc_base(0)), (0, TIDE, loc_base(0)),
                                  (0, CRAB, loc_base(0))])
    spare["exh"] = True
    actions.ready(g, spare["id"])
    check("two abilities that triggered at the same time are both queued "
          "(383.3)", len(g.s.trigs) == 2)
    run_triggers(g)
    pending = g.s.pending
    check("their controller is asked an `order` decision, one at a time "
          "(383.3.d)",
          pending is not None and pending["kind"] == "order"
          and len(pending["options"]) == 2,
          "%r" % (pending and pending["kind"],))
    chosen = pending["options"][1][0]
    g.answer(chosen)
    check("the one they chose goes on the Chain first (383.3.d)",
          g.s.chain and g.s.chain[0]["src_id"] in (one["id"], two["id"]))

    # 383.3.d.1 / 303.2.a: across seats the order is Turn Order, not a choice.
    abilities.clear()
    abilities.register(TIDE, Ability(
        "triggered", text="when a unit is readied, gain 1 XP",
        trigger=Trigger(("readied",), who="any"), effect=xp_effect()))
    order = []
    for first in (0, 1):
        g, (mine, theirs, spare) = board(
            [(0, TIDE, loc_base(0)), (1, TIDE, loc_base(1)), (0, CRAB, loc_base(0))],
            first=first)
        spare["exh"] = True
        actions.ready(g, spare["id"])
        run_triggers(g)
        order.append([item["ctrl"] for item in g.s.chain])
    check("across seats the Turn Player's triggers go on the Chain first "
          "(383.3.d.1, 303.2.a)",
          order[0] == [0, 1] and order[1] == [1, 0], "%r" % (order,))
    abilities.clear()


def _created(check):
    """Reflexive (386-388), Delayed (389-392), Linked (393-397), unless-pays."""
    abilities.clear()
    reflex = Ability("reflexive", text="Do this: gain 1 XP", effect=xp_effect())
    abilities.register(TIDE, Ability("passive", modifier=might_mod(0)), reflex)
    g, (unit,) = board([(0, TIDE, loc_base(0))])
    ctx = {"seat": 0, "src": {"oid": unit["id"], "name": TIDE, "unit": unit},
           "ev": {}, "item": None}
    made = abilities.reflex(g, ctx, (TIDE, 1), times=3)
    check("a Reflexive Trigger adds one Pending Item per repetition, in order "
          "(387.1.a, 388.1)",
          len(made) == 3 and all(i["pending"] for i in made)
          and [i["id"] for i in g.s.chain] == [i["id"] for i in made])
    check("and an ability that is not a Reflexive Trigger cannot be one (387)",
          _h().raises(lambda: abilities.reflex(g, ctx, (TIDE, 0)),
                      "not a reflexive trigger"))

    # 389-392: delayed.
    abilities.clear()
    abilities.register(BROKER, Ability(
        "triggered", text="when you conquer, gain 1 XP at end of turn",
        trigger=Trigger(("conquer",), who="you"),
        effect=lambda gg, c: abilities.delay(
            gg, c["seat"], (BROKER, 1), "end_of_turn", window="this_turn",
            src_id=c["src"]["oid"])),
        Ability("delayed", text="at the end of this turn, gain 1 XP",
                trigger=Trigger(("end_of_turn",), who="any"), effect=xp_effect()))
    g, (unit,) = board([(0, BROKER, loc_base(0))])
    abilities.delay(g, 0, (BROKER, 1), "end_of_turn", window="this_turn",
                    src_id=unit["id"])
    check("a Delayed Ability waits on the state, not on its source (389, 392)",
          len(g.s.delayed) == 1 and not g.s.trigs)
    actions.to_trash(g, unit["id"])
    abilities.emit(g, "end_of_turn", seat=0, turn=g.s.turn)
    check("and fires when its time comes even though its source has left the "
          "Board (392)", len(g.s.trigs) == 1, "%d queued" % len(g.s.trigs))
    check("and is gone once it has fired — it was "
          "\"the next\", not \"every\" (390.3, 391)", not g.s.delayed)

    g, (unit,) = board([(0, BROKER, loc_base(0))])
    abilities.delay(g, 0, (BROKER, 1), "end_of_turn", window="this_turn",
                    src_id=unit["id"])
    check("a Delayed Ability whose window was this turn is retired at the "
          "Expiration Step (317.2.d, 391)",
          abilities.retire_delayed(g, "this_turn") and not g.s.delayed)
    check("a window the framework does not carry is refused rather than "
          "silently never firing (390.2)",
          _h().raises(lambda: abilities.delay(g, 0, (BROKER, 1), "end_of_turn",
                                              window="next_week"), "not a window"))
    check("and so is a Delayed Ability keyed to something that is not an event "
          "(383, 390.2)",
          _h().raises(lambda: abilities.delay(g, 0, (BROKER, 1), "delayed_next"),
                      "not a trigger event"))

    # 393-397: linked.
    abilities.clear()
    first = Ability("triggered", text="when I die, buff two units", link="pair",
                    trigger=Trigger(("die",), who="me"), effect=xp_effect())
    second = Ability("triggered", text="then ready THOSE units", link="pair",
                     trigger=Trigger(("die",), who="me"), effect=xp_effect())
    abilities.register(PYKE, first, second)
    g, (unit, a, b, c) = board([(0, PYKE, loc_base(0)), (0, CRAB, loc_base(0)),
                                (0, CRAB, loc_base(0)), (0, TIDE, loc_base(0))])
    item = {"id": "c9", "ctrl": 0, "name": PYKE, "kind": "ability",
            "pending": False, "loc": "", "abil": (PYKE, 0), "src_id": unit["id"],
            "ev": (), "sub": "triggered", "step": 6}
    ctx = {"seat": 0, "src": {"oid": unit["id"], "name": PYKE, "unit": unit},
           "ev": {}, "item": item}
    abilities.link_record(g, ctx, [a["id"], b["id"]])
    item2 = dict(item, abil=(PYKE, 1))
    ctx2 = dict(ctx, item=item2)
    affected = abilities.linked_objects(g, ctx2)
    check("a component Linked Ability sees exactly what its set affected "
          "(394.1, 397)", affected == (a["id"], b["id"]), "%r" % (affected,))
    check("and nothing else — 397 bounds it to the objects its set touched",
          c["id"] not in affected)
    check("an ability with no link name cannot read a Linked set's record (394)",
          _h().raises(lambda: abilities.linked_objects(
              g, dict(ctx, item=dict(item, abil=(TIDE, 0)))), "no ability"))

    # "unless [a player] pays" — a `cost` decision for the OTHER seat.
    abilities.clear()
    abilities.register(PYKE, Ability(
        "triggered", text="when I die, gain 1 XP unless they pay 1 XP",
        trigger=Trigger(("die",), who="me"),
        unless=("opponent", Cost(xp=1), "let them gain 1 XP"),
        effect=lambda gg, c: None if c["paid"] else actions.gain_xp(gg, c["seat"], 1)))
    g, (unit,) = board([(0, PYKE, loc_base(0))])
    actions.gain_xp(g, 1, 1)
    actions.to_trash(g, unit["id"])
    g.auto_trivial = False
    asked = None
    for _ in range(40):
        d = g.step()
        if d.terminal or d.kind == "main":
            break
        SEEN.add(d.kind)
        if d.kind == "cost" and d.seat == 1:
            asked = d
            g.answer(next(o for o in d.options if o.key[0] == "pay"))
            continue
        g.answer(d.options[0])
    check("\"unless [a player] pays\" asks a `cost` decision of THAT seat "
          "(355.10.c.1, 203)",
          asked is not None and asked.seat == 1,
          "asked seat %r" % (asked.seat if asked else None))
    check("and paying it changes what the ability does (203)",
          g.s.xp[0] == 0 and g.s.xp[1] == 0, "XP %r" % (g.s.xp,))

    g, (unit,) = board([(0, PYKE, loc_base(0))])
    actions.gain_xp(g, 1, 1)
    actions.to_trash(g, unit["id"])
    drive(g, prefer=("decline",))
    check("declining gets the ability's effect instead (203.3)",
          g.s.xp[0] == 1 and g.s.xp[1] == 1, "XP %r" % (g.s.xp,))
    abilities.clear()


def _events(check):
    """Every declared trigger event, and the decision kinds this slice emits."""
    abilities.clear()
    raised = set()
    for name in kernel_modules():
        with open(os.path.join(HERE, name), encoding="utf-8") as fh:
            raised.update(re.findall(r'emit\(g, "(\w+)"', fh.read()))
    declared = set(abilities.EVENTS)
    check("every trigger event this framework declares is raised somewhere in "
          "the kernel (383, census 3)",
          declared <= raised,
          "never raised: %s" % (", ".join(sorted(declared - raised)) or "none"))
    check("and nothing raises an event the vocabulary does not declare",
          raised <= declared,
          "undeclared: %s" % (", ".join(sorted(raised - declared)) or "none"))
    check("the census's `nth_time` and `delayed_next` are NOT events — one is a "
          "frequency (383.1.b) and one is a window (390.2)",
          "nth_time" not in declared and "delayed_next" not in declared
          and "next" in abilities.WINDOWS)

    check("`optional`, `order` and `cost` are declared as emitted (383.3.a, "
          "383.3.d, 404.2)",
          set(("optional", "order", "cost")) <= set(EMITTED))
    check("and this suite has actually watched each of them be emitted, so the "
          "claim is evidence",
          set(("optional", "order", "cost")) <= SEEN,
          "seen: %s" % ", ".join(sorted(SEEN)))

    # An option nobody offered is still refused, for the new kinds as for the
    # old ones. Checked on a real `order` decision rather than a built one.
    abilities.register(TIDE, Ability(
        "triggered", text="when a unit is readied, gain 1 XP",
        trigger=Trigger(("readied",), who="any"), effect=xp_effect()))
    g, (one, two, spare) = board([(0, TIDE, loc_base(0)), (0, TIDE, loc_base(0)),
                                  (0, CRAB, loc_base(0))])
    spare["exh"] = True
    actions.ready(g, spare["id"])
    run_triggers(g)
    check("an `order` decision refuses an option it did not offer",
          _h().raises(lambda: g.answer(("next", "t999")),
                      "not one of the legal options"))
    abilities.clear()

    # The demo set is the soak's fixture, and a demo ability on a card no deck
    # plays proves nothing while reporting that it does.
    abilities.clear()
    check("every card the hand-built ability set names is still in the fixture "
          "decks", not demo.missing(list(fixtures.pair())),
          "gone: %s" % (", ".join(demo.missing(list(fixtures.pair()))) or "none"))
    demo.attach()
    try:
        kinds = set(a.kind for _n, abils in demo.build() for a in abils)
        check("and it covers a passive, an activated, a triggered, a delayed "
              "and three replacement kinds (361.1)",
              set(("passive", "activated", "triggered", "delayed",
                   "enters_modified", "cost_replacement", "would")) <= kinds,
              ", ".join(sorted(kinds)))
        ends = set()
        for seed in range(24):
            g = Game.new(*fixtures.pair(), seed=seed, hash_log=False)
            policies.play(g, policies.random_pair(seed))
            ends.add(g.s.end_reason)
        check("and 24 random games with those abilities attached all end by a "
              "named rule (472, 431.3)",
              bool(ends) and all("472" in r or "431" in r for r in ends),
              "; ".join(sorted(ends))[:110])
    finally:
        demo.detach()
    check("the hand-built set detaches again, so nothing after it runs with "
          "abilities attached", not abilities.REGISTRY,
          "%d name(s) still registered" % len(abilities.REGISTRY))

    # A vanilla game still emits none of the three, which is what makes the
    # EMITTED check above a statement about ABILITIES rather than about cards.
    kinds = set()
    probe = Game.new(*fixtures.pair(), seed=5, first=0, hash_log=False)
    pol = policies.random_pair("vanilla-kinds")
    for _ in range(400):
        d = probe.step()
        if d.terminal:
            break
        kinds.add(d.kind)
        probe.answer(pol[d.seat](d))
    check("a vanilla game emits no ability decision at all, because a vanilla "
          "card has no abilities (362)",
          not (kinds & set(("optional", "order", "cost", "modal"))),
          "emitted: %s" % ", ".join(sorted(kinds)))


# =======================================================================
# replacement effects
# =======================================================================

def engine_replacements(check):
    abilities.clear()
    try:
        _replacement_shapes(check)
        _replacement_rules(check)
    finally:
        abilities.clear()


def _replacement_shapes(check):
    st = _h()

    # 1. enters_modified (17 gauntlet cards) — 369.3.
    abilities.clear()
    abilities.register(DREDGER, Ability(
        "enters_modified", text="I enter ready",
        # "I enter ready" has nothing to say about an entry that is already
        # ready, which is also what stops it applying to its own output.
        applies=lambda g, ev, src: ev.get("name") == DREDGER and ev["exh"],
        replace=lambda g, ev, src: dict(ev, exh=False)))
    g, _ = board([])
    unit = actions.put_into_play(g, 0, DREDGER, loc_base(0), True, "chain")
    check("`enters_modified`: a unit that would enter exhausted enters ready "
          "(367, 369.3, 359.2.c)", unit is not None and not unit["exh"])

    # 2. as_enters (3 cards) — 370.1.b.1: the event PLUS the action.
    abilities.clear()
    marks = []
    abilities.register(DREDGER, Ability(
        "as_enters", text="as I enter, note it",
        applies=lambda g, ev, src: ev.get("name") == DREDGER and not marks,
        replace=lambda g, ev, src: (marks.append(ev["name"]), ev)[1]))
    g, _ = board([])
    unit = actions.put_into_play(g, 0, DREDGER, loc_base(0), True, "chain")
    check("`as_enters`: the described event happens AND the game action beside "
          "it (370.1.b.1)",
          marks == [DREDGER] and unit is not None and unit["exh"])

    # 3. instead (15 cards) — 369: the event is replaced away.
    abilities.clear()
    abilities.register(PYKE, Ability(
        "instead", text="instead of dying, I am banished",
        applies=lambda g, ev, src: ev["ev"] == "die" and ev["oid"] == src["oid"],
        replace=lambda g, ev, src: _banish_instead(g, ev)))
    g, (unit,) = board([(0, PYKE, loc_base(0))])
    actions.to_trash(g, unit["id"])
    check("`instead`: the qualifying event does not happen and the replacement "
          "does (369, 370.1.b)",
          PYKE in g.s.banished[0] and PYKE not in g.s.trash[0],
          "trash %r banished %r" % (g.s.trash[0][-1:], g.s.banished[0][-1:]))

    # 4. would (7 cards) — 369, modifying rather than substituting.
    abilities.clear()
    abilities.register(AKALI, Ability(
        "would", text="damage dealt to me is 1 less",
        applies=lambda g, ev, src: (ev["ev"] == "damage"
                                    and ev["oid"] == src["oid"] and ev["n"] > 0),
        replace=lambda g, ev, src: dict(ev, n=ev["n"] - 1)))
    g, (unit,) = board([(0, AKALI, loc_base(0))])
    event = replacements.apply(g, {"ev": "damage", "oid": unit["id"], "n": 3,
                                   "seat": 0, "name": AKALI})
    check("`would`: the event happens with the replacement's changes on it (369)",
          event is not None and event["n"] == 2, "%r" % (event and event["n"],))

    # 5. cost_replacement (19 cards) — 356.3/356.4.
    abilities.clear()
    g, _ = board([])
    spell = a_spell(g.decks[0])
    printed = actions.cost_of(spell)["energy"]
    abilities.register(SHARP, Ability(
        "cost_replacement", text="your spells cost 1 less",
        applies=lambda gg, ev, src: turn.category(ev.get("name", "")) == "spell",
        replace=lambda gg, ev, src: ("energy", -1)))
    st.put(g, 0, SHARP, loc_base(0))
    check("`cost_replacement`: a discount moves the component it names "
          "(356.4.b, 356.4.c)",
          actions.total_cost(g, 0, spell)["energy"] == max(printed - 1, 0),
          "%d -> %d" % (printed, actions.total_cost(g, 0, spell)["energy"]))
    check("and 206 keeps the PRINTED cost available to anything that asks",
          actions.cost_of(spell)["energy"] == printed)

    # 6. ignoring_cost (8 cards) — 356.1.b.
    abilities.clear()
    abilities.register(SHARP, Ability(
        "ignoring_cost", text="play your spells ignoring their Energy cost",
        applies=lambda gg, ev, src: turn.category(ev.get("name", "")) == "spell",
        replace=lambda gg, ev, src: "energy"))
    g, _ = board([(0, SHARP, loc_base(0))])
    cost = actions.total_cost(g, 0, spell)
    check("the spell this check uses has a Power cost, so 356.1.b.2 has "
          "something to leave alone",
          actions.cost_of(spell)["power"] > 0,
          "%s costs %dE %dP" % (spell, actions.cost_of(spell)["energy"],
                                actions.cost_of(spell)["power"]))
    check("`ignoring_cost`: naming one component zeroes only that one "
          "(356.1.b.2)",
          cost["energy"] == 0 and cost["power"] == actions.cost_of(spell)["power"],
          "%dE %dP" % (cost["energy"], cost["power"]))
    abilities.clear()


def _banish_instead(g, event):
    from . import actions as _a
    unit = g.s.unit(event["oid"])
    _a.banish(g, unit["id"])
    return None


def _replacement_rules(check):
    # 370.2: once per event.
    abilities.clear()
    hits = []

    def soften(g, ev, src):
        hits.append(1)
        return dict(ev, n=ev["n"] - 1)

    abilities.register(AKALI, Ability(
        "would", text="damage dealt to me is 1 less",
        applies=lambda g, ev, src: ev["ev"] == "damage" and ev["n"] > 0,
        replace=soften))
    g, (unit,) = board([(0, AKALI, loc_base(0))])
    event = replacements.apply(g, {"ev": "damage", "oid": unit["id"], "n": 4,
                                   "seat": 0, "name": AKALI})
    check("a Replacement Effect applies ONCE to an event, however many times it "
          "would still qualify (370.2)",
          len(hits) == 1 and event["n"] == 3, "%d application(s)" % len(hits))

    # 054.1: can't beats can.
    abilities.clear()
    order = []
    # Each refuses itself once it has run. 370.2 would do that for them, and
    # these two exist to watch a DIFFERENT rule — so they must not depend on the
    # one whose mutant would otherwise loop them against each other forever.
    abilities.register(AKALI, Ability(
        "would", text="a permissive replacement",
        applies=lambda g, ev, src: ev["ev"] == "damage" and "can" not in order,
        replace=lambda g, ev, src: (order.append("can"), ev)[1]))
    abilities.register(TIDE, Ability(
        "would", text="a forbidding replacement", forbids=True,
        applies=lambda g, ev, src: ev["ev"] == "damage" and "cant" not in order,
        replace=lambda g, ev, src: (order.append("cant"), ev)[1]))
    g, (akali, tide) = board([(0, AKALI, loc_base(0)), (0, TIDE, loc_base(0))])
    replacements.apply(g, {"ev": "damage", "oid": akali["id"], "n": 2,
                           "seat": 0, "name": AKALI})
    check("a Replacement Effect that forbids is applied before one that permits "
          "(054.1)", order[:1] == ["cant"], "%r" % (order,))

    # 371.1: "once each turn" caps how many EVENTS it applies to.
    abilities.clear()
    abilities.register(AKALI, Ability(
        "would", text="once each turn, damage dealt to me is 1 less",
        frequency=("limit", 1, "turn"),
        applies=lambda g, ev, src: (ev["ev"] == "damage"
                                    and ev["oid"] == src["oid"] and ev["n"] > 0),
        replace=lambda g, ev, src: dict(ev, n=ev["n"] - 1)))
    g, (unit,) = board([(0, AKALI, loc_base(0))])
    one = replacements.apply(g, {"ev": "damage", "oid": unit["id"], "n": 3,
                                 "seat": 0, "name": AKALI})
    two = replacements.apply(g, {"ev": "damage", "oid": unit["id"], "n": 3,
                                 "seat": 0, "name": AKALI})
    check("a \"once each turn\" Replacement Effect applies to one event and not "
          "the next (371.1)",
          one["n"] == 2 and two["n"] == 3, "%d then %d" % (one["n"], two["n"]))
    turn.begin_turn(g)
    three = replacements.apply(g, {"ev": "damage", "oid": unit["id"], "n": 3,
                                   "seat": 0, "name": AKALI})
    check("and its allowance comes back with the turn (371.1)", three["n"] == 2)

    # 721.2: an Inactive replacement does not apply.
    abilities.clear()
    abilities.register(AKALI, Ability(
        "would", text="[Level 5] damage dealt to me is 1 less",
        gate=Gate("Level", 5),
        applies=lambda g, ev, src: (ev["ev"] == "damage"
                                    and ev["oid"] == src["oid"] and ev["n"] > 0),
        replace=lambda g, ev, src: dict(ev, n=ev["n"] - 1)))
    g, (unit,) = board([(0, AKALI, loc_base(0))])
    closed = replacements.apply(g, {"ev": "damage", "oid": unit["id"], "n": 3,
                                    "seat": 0, "name": AKALI})
    actions.gain_xp(g, 0, 5)
    opened = replacements.apply(g, {"ev": "damage", "oid": unit["id"], "n": 3,
                                    "seat": 0, "name": AKALI})
    check("an Inactive Replacement Effect does not apply, and applies once its "
          "gate opens (721.2, 727.1.b)",
          closed["n"] == 3 and opened["n"] == 2,
          "%d then %d" % (closed["n"], opened["n"]))

    # 370.1.a: the replaceable set is closed, and a name outside it is refused.
    check("an event outside the replaceable vocabulary is refused rather than "
          "silently unreplaceable (370.1.a)",
          _h().raises(lambda: replacements.apply(g, {"ev": "sneeze"}),
                      "not a replaceable event"))

    # And every name INSIDE it is one some rule builds. A vocabulary entry with
    # no call site is a replacement a script can be written against and that can
    # never fire — the same silent hole `engine_abilities` scans for on the
    # trigger side.
    built = set()
    for name in kernel_modules():
        with open(os.path.join(HERE, name), encoding="utf-8") as fh:
            built.update(re.findall(r'replacements\.apply\(g, \{"ev": "(\w+)"',
                                    fh.read()))
    check("every replaceable event is one some rule actually builds (370.1.a)",
          set(replacements.EVENTS) == built,
          "declared-only: %s; built-only: %s"
          % (", ".join(sorted(set(replacements.EVENTS) - built)) or "none",
             ", ".join(sorted(built - set(replacements.EVENTS))) or "none"))

    # Combat damage really does go through the pipeline.
    abilities.clear()
    abilities.register(AKALI, Ability(
        "would", text="damage dealt to me is reduced to 0",
        applies=lambda g, ev, src: (ev["ev"] == "damage"
                                    and ev["oid"] == src["oid"] and ev["n"] > 0),
        replace=lambda g, ev, src: dict(ev, n=0)))
    g, (mine,) = board([(0, AKALI, loc_base(0))])
    event = replacements.apply(g, {"ev": "damage", "oid": mine["id"], "n": 9,
                                   "seat": 0, "name": AKALI})
    marked = mine["dmg"]
    check("combat damage is a replaceable event and the replacement decides "
          "how much is marked (370.1.c, 465.2.d)",
          event["n"] == 0 and marked == 0)
    abilities.clear()


# =======================================================================
# layers
# =======================================================================

def engine_layers(check):
    abilities.clear()
    try:
        _layer_order(check)
        _durations(check)
        _timestamps(check)
    finally:
        abilities.clear()


def _layer_order(check):
    abilities.clear()
    g, (unit,) = board([(0, TIDE, loc_base(0))])
    printed = unit["might"]

    # Created in the "wrong" order on purpose: the +2 first, the assignment
    # second. 477 says the assignment still applies first.
    layers.new_effect(g, "give_might", n=2, targets=(unit["id"],), until="permanent")
    layers.new_effect(g, "set_might", n=1, targets=(unit["id"],), until="permanent")
    check("a Might ASSIGNMENT applies in layer 1 and the arithmetic in layer 3, "
          "whatever order they were created in (477.1.a.1, 477.3)",
          g.s.might_of(unit) == 3, "Might %d, printed %d" % (g.s.might_of(unit),
                                                             printed))

    # 477.3.e: increases (477.3.e.1) before decreases (477.3.e.2). Visible
    # because 477.3.c forbids increasing by a negative amount, so a decrease
    # that lands first would floor the value before the increase arrives.
    abilities.clear()
    g, (unit,) = board([(0, CRAB, loc_base(0))])
    layers.new_effect(g, "give_might", n=-1, targets=(unit["id"],),
                      until="permanent")
    layers.new_effect(g, "give_might", n=3, targets=(unit["id"],), until="permanent")
    # Asked of the ENGINE's own ordering function, not of a sort this file
    # repeats. A check that re-implements the rule it is checking agrees with
    # itself whatever the engine does, which is how this one passed while the
    # engine was free to apply them in either order.
    applied = [e["n"] for e in layers.ordered(
        [e for e in g.s.effects if e["op"] == "give_might"], layers.ARITHMETIC)]
    check("within the arithmetic layer, increases are applied before decreases "
          "(477.3.e.1, 477.3.e.2)", applied == [3, -1], "%r" % (applied,))
    check("and the total is the same either way — the order is pinned because "
          "477.3.b's snapshotting is what will make it visible",
          g.s.might_of(unit) == unit["might"] + 2)

    # 477: the order the layers run in is observable in WHEN an effect becomes
    # applicable, and nowhere else — a layer-2 grant whose condition a layer-3
    # effect creates cannot apply in the same sequence the +Might does, so it
    # lands on the next one (476.2). Running the layers in any other order
    # settles a sequence earlier, with the grant already in place.
    abilities.clear()

    def tank_the_big(g, src):
        return [{"op": "grant", "kw": "tank", "n": 1, "targets": tuple(
            u["id"] for u in g.s.units if g.s.might_of(u) >= 4)}]

    abilities.register(SHARP, Ability("passive", text="units with Might 4+ gain Tank",
                                      modifier=tank_the_big))
    g, (source, small) = board([(0, SHARP, loc_base(0)), (0, CRAB, loc_base(0))])
    layers.new_effect(g, "give_might", n=4, targets=(small["id"],), until="permanent")
    sequences = layers.recompute(g)
    check("the layers run in the order 477 lists them, so a layer-2 grant whose "
          "condition a layer-3 effect creates lands one sequence later "
          "(477, 476.2)",
          layers.has_keyword(small, "tank") and sequences >= 3,
          "settled in %d sequence(s), Tank %s"
          % (sequences, layers.has_keyword(small, "tank")))

    # 477.2: a keyword grant is layer 2, and 807.2 sums it onto the printed one.
    abilities.clear()
    g, (unit,) = board([(0, TIDE, loc_base(0))])
    unit["assault"] = 1
    layers.new_effect(g, "grant", kw="assault", n=2, targets=(unit["id"],),
                      until="permanent")
    check("a granted keyword SUMS onto the printed instance (477.2.a, 807.2)",
          layers.keyword_value(unit, "assault") == 3,
          "%d" % layers.keyword_value(unit, "assault"))
    unit["role"] = "attacker"
    check("and the sum is what reaches Might while the designation holds "
          "(807.1.c, 807.1.d)",
          g.s.might_of(unit) == unit["might"] + 3)
    unit["role"] = None

    layers.new_effect(g, "grant", kw="tank", targets=(unit["id"],),
                      until="permanent")
    check("a boolean keyword grant reads as having it (477.2.a, 815)",
          layers.has_keyword(unit, "tank") and not layers.has_keyword(unit, "backline"))
    layers.new_effect(g, "remove", kw="tank", targets=(unit["id"],),
                      until="permanent")
    check("and removing rules text is the same layer, applied by Timestamp "
          "(477.2.a, 480.3)", not layers.has_keyword(unit, "tank"))

    # 477.1.a: Controller is a trait, and a trait a recomputation can put back.
    abilities.clear()
    g, (unit,) = board([(0, TIDE, loc_base(0))])
    effect = layers.new_effect(g, "set_controller", n=1, targets=(unit["id"],),
                               until="this_turn")
    check("Controller is altered in layer 1 (477.1.a)", unit["ctrl"] == 1)
    layers.expire(g, "this_turn")
    check("and goes back to the owner when the effect ends (477.1.a, 476)",
          unit["ctrl"] == unit["owner"])
    del effect

    check("an operation with no layer in 477 is refused rather than landing in "
          "whichever one the author assumed",
          _h().raises(lambda: layers.new_effect(g, "make_it_blue"),
                      "not a layer operation"))
    check("and a duration the framework does not carry is refused too (477.3)",
          _h().raises(lambda: layers.new_effect(g, "give_might", n=1,
                                                until="forever"),
                      "not a duration"))
    abilities.clear()


def _durations(check):
    # 702-705 vs 477: a Buff and a `give_might` both raise Might and are
    # different objects. The Expiration Step is where that shows.
    abilities.clear()
    g, (buffed, modded) = board([(0, TIDE, loc_base(0)), (0, TIDE, loc_base(0))])
    actions.buff(g, buffed["id"])
    actions.give_might(g, [modded["id"]], 1, until="this_turn")
    before = (g.s.might_of(buffed), g.s.might_of(modded))
    layers.expire(g, "this_turn")
    after = (g.s.might_of(buffed), g.s.might_of(modded))
    check("a \"this turn\" continuous effect expires and a Buff does not — they "
          "are different objects (477, 317.2.d, 702, 705)",
          before == (buffed["might"] + 1, modded["might"] + 1)
          and after == (buffed["might"] + 1, modded["might"]),
          "%r -> %r" % (before, after))

    check("a second Buff is not placed on a Unit that already has one "
          "(702.3.a, 426.1.b.1)",
          not actions.buff(g, buffed["id"]) and buffed["buffs"] == 1)
    check("and a Buff cannot be spent from a Unit that does not have one "
          "(702.2.b.1)",
          _h().raises(lambda: actions.spend_buff(g, modded["id"]),
                      "does not have one"))

    # 466.7 / census 5b: `this_combat`.
    abilities.clear()
    g, (unit,) = board([(0, TIDE, loc_base(0))])
    actions.give_might(g, [unit["id"]], 2, until="this_combat")
    live = g.s.might_of(unit)
    layers.expire(g, "this_combat")
    check("a `this_combat` effect ends with the combat and not with the turn "
          "(477, 466.7)",
          live == unit["might"] + 2 and g.s.might_of(unit) == unit["might"])

    # `until_event`.
    abilities.clear()
    g, (unit,) = board([(0, TIDE, loc_base(0))])
    layers.new_effect(g, "give_might", n=2, targets=(unit["id"],),
                      until="until_event", ev="end_of_turn")
    live = g.s.might_of(unit)
    abilities.emit(g, "end_of_turn", seat=0, turn=g.s.turn)
    check("an `until_event` effect ends when its event is raised (477)",
          live == unit["might"] + 2 and g.s.might_of(unit) == unit["might"])

    # 423: a Stunned unit contributes no Might and still needs its full Might.
    abilities.clear()
    from . import combat
    g, (unit,) = board([(0, TIDE, loc_base(0))])
    actions.stun(g, unit["id"])
    check("a Stunned Unit contributes no Might to the Damage Step (423.1.b)",
          combat.damage_pool(g.s, [unit]) == 0,
          "pool %d" % combat.damage_pool(g.s, [unit]))
    check("and still needs its FULL Might in damage to die (423.1.c)",
          combat.minimum_lethal(g.s, unit) == unit["might"])
    check("Stunning an already Stunned Unit is not a second event (423.1.a.1)",
          not actions.stun(g, unit["id"]))
    abilities.clear()


def _timestamps(check):
    # 480.3: within one layer, the earliest Timestamp applies first. Made
    # visible with two assignments, where only the last one applied shows.
    abilities.clear()
    g, (unit,) = board([(0, TIDE, loc_base(0))])
    layers.new_effect(g, "set_might", n=7, targets=(unit["id"],), until="permanent")
    layers.new_effect(g, "set_might", n=1, targets=(unit["id"],), until="permanent")
    check("two effects in one layer apply in Timestamp order, so the later one "
          "wins (480.1, 480.3)", g.s.might_of(unit) == 1,
          "Might %d" % g.s.might_of(unit))

    # 480.2: text that goes Inactive loses its Timestamp and gets a new one.
    abilities.clear()
    abilities.register(TIDE, Ability("passive", text="[Level 2] +1 Might",
                                     gate=Gate("Level", 2), modifier=might_mod(1)))
    g, (unit,) = board([(0, TIDE, loc_base(0))])
    check("an Inactive passive holds no Timestamp at all (480.2, 721.2)",
          not g.s.stamps, "%r" % (g.s.stamps,))
    actions.gain_xp(g, 0, 2)
    first = dict(g.s.stamps)
    actions.spend_xp(g, 0, 2)
    check("becoming Inactive loses it (480.2)", first and not g.s.stamps)
    actions.gain_xp(g, 0, 2)
    check("and coming back establishes a NEW one, later than the old (480.2)",
          g.s.stamps and list(g.s.stamps.values()) > list(first.values()),
          "%r then %r" % (sorted(first.values()), sorted(g.s.stamps.values())))

    # 476.2: the fixpoint really iterates. A passive whose scope depends on a
    # trait the layers produce settles by recurring the whole sequence.
    abilities.clear()

    def mighty_only(g, src):
        return [{"op": "give_might", "n": 1, "targets": tuple(
            u["id"] for u in g.s.units if g.s.might_of(u) >= 3)}]

    abilities.register(SHARP, Ability("passive", text="units with Might 3+ get +1",
                                      modifier=mighty_only))
    g, (source, small) = board([(0, SHARP, loc_base(0)), (0, TIDE, loc_base(0))])
    passes = layers.recompute(g)
    check("the layers are a fixpoint and recur until nothing changes (476.2)",
          passes > 1, "settled in %d pass(es)" % passes)
    check("and the effect's scope is taken from the traits the layers produced, "
          "not from the printed ones (476.1)",
          g.s.might_of(source) == source["might"] + 1
          and g.s.might_of(small) == small["might"],
          "%d and %d" % (g.s.might_of(source), g.s.might_of(small)))

    # 476.1: "only a single time across all sequences". The recursion above is
    # what makes this worth pinning — an effect that is re-applied on every
    # sequence would double, and the board would settle on the wrong number
    # rather than crash.
    abilities.clear()
    g, (unit,) = board([(0, TIDE, loc_base(0))])
    layers.new_effect(g, "give_might", n=2, targets=(unit["id"],), until="permanent")
    once = g.s.might_of(unit)
    layers.recompute(g)
    layers.recompute(g)
    check("an effect applies a single time however many sequences the layers "
          "run (476.1)",
          once == unit["might"] + 2 and g.s.might_of(unit) == once,
          "Might %d then %d" % (once, g.s.might_of(unit)))
    abilities.clear()
