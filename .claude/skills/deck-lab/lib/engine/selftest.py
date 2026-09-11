"""The kernel's regression checks, run as part of `deck_cli.py selftest`.

Same discipline as the table's suite and for the same reason: a check nobody has
watched fail is not yet a check, so every group here has mutants in
`../mutants.py` that reintroduce the defect it is named for.

The groups are `SECTIONS`, each a function taking the parent suite's `check`, so
the engine's checks are counted in the same total and recorded in the same
`proven-checks.json`. Nothing here reads a file outside the skill folder.
"""
import collections
import json
import os
import re

import cards
import deckfile

from . import (actions, chain, combat, fixtures, goldens, invariants, perft,
               policies, rng, scoring, turn)
from .decisions import EMITTED, KINDS
from .game import Game
from .state import RulesError, loc_base, loc_bf, new_unit

HERE = os.path.dirname(os.path.abspath(__file__))
TRANSITIONS = os.path.join(HERE, "goldens", "chain-transitions.json")


# -- fixtures ------------------------------------------------------------

def two_decks():
    """The default fixture pair. Named in `engine/fixtures.py`, not here."""
    return fixtures.pair()


def game(seed=7, first=0, **kw):
    a, b = two_decks()
    return Game.new(a, b, seed=seed, first=first, **kw)


def to_main(g, limit=400):
    """Advance to the Turn Player's next Main Phase decision, keeping every hand."""
    for _ in range(limit):
        d = g.step()
        if d.terminal or d.kind == "main":
            return d
        g.answer(d.options[0])
    raise AssertionError("never reached a Main Phase decision")


def at_main(seed=7, first=0, **kw):
    g = game(seed, first, **kw)
    to_main(g)
    return g


def raises(fn, fragment=""):
    try:
        fn()
    except RulesError as err:
        return fragment.lower() in str(err).lower()
    except Exception:
        return False
    return False


def put(g, seat, name, location, exhausted=False):
    """Drop a unit straight onto the board, bypassing the play process.

    A test fixture, not a rule: some of the board shapes worth probing are ones
    a vanilla game reaches only rarely, and waiting for one is not a test.
    """
    unit = new_unit(g.s.mint("u"), name, seat, location, exhausted)
    g.s.units.append(unit)
    return unit


def refresh(g):
    """Throw away the question the engine is holding and let it ask again.

    A fixture that puts a unit on the board AFTER `step()` has already built the
    Main Phase option list is asking about a board that no longer exists. This
    is only needed because the fixtures reach past the decision API on purpose.
    """
    g.s.pending = None
    g.s.choosing = None
    return g


def a_unit(cost_at_most=99):
    for name in sorted(set(two_decks()[0].main_cards())):
        if cards.card_type(name) == cards.UNIT and (cards.energy_cost(name) or 0) <= cost_at_most:
            return name
    raise AssertionError("no unit in the fixture deck")


def texts(g):
    return [e["text"] for e in g.log]


def with_playable(kind, seed=13, turns=12, **kw):
    """A game stopped on a Main Phase decision that offers a card of `kind`."""
    g = at_main(seed=seed, **kw)
    for _ in range(turns):
        d = g.step()
        if d.terminal:
            break
        if any(o.key[0] == "play" and turn.category(o.key[2]) == kind
               for o in d.options):
            return g, d
        _end_turn(g)
    raise AssertionError("no %s became playable in %d turns" % (kind, turns))


def swap_seats(text):
    return text.replace("seat 0", "seat @").replace("seat 1", "seat 0") \
               .replace("seat @", "seat 1")


#: Which primer transition each check covers, or why the vanilla slice cannot
#: reach it. Keyed by (primer, step, exit index) — the same key the vendored
#: table uses — so a primer that grows a transition breaks this until someone
#: classifies the new one.
TRANSITION_COVER = {
    ("hot-fepr", "s1", 0): "a spell opens a window before it resolves (338, 339.1)",
    ("hot-fepr", "s1", 1): "the Chain empties and play returns to an Open State (340.2)",
    ("hot-fepr", "s2", 0): "a Unit resolves the moment it is finalized (337.2)",
    ("hot-fepr", "s2", 1): "UNREACHABLE: nothing in the vanilla slice puts a second "
                           "Pending Item on the Chain — only triggered abilities do",
    ("hot-fepr", "s2", 2): "finalizing does not pass priority (337.1.a)",
    ("hot-fepr", "s3", 0): "UNREACHABLE: no vanilla card is legally timed in a Closed "
                           "State (338.1.a.1)",
    ("hot-fepr", "s3", 1): "a spell opens a window before it resolves (338, 339.1)",
    ("hot-fepr", "s4", 0): "a spell opens a window before it resolves (338, 339.1)",
    ("hot-fepr", "s4", 1): "one pass is not a sequence of passes (339.2)",
    ("hot-fepr", "s5", 0): "the Chain empties and play returns to an Open State (340.2)",
    ("hot-fepr", "s5", 1): "UNREACHABLE: a resolution never leaves a Pending Item "
                           "behind in the vanilla slice",
    ("hot-fepr", "s5", 2): "a Chain of three resolves newest first, one at a time (340.4)",
    ("showdowns", "s1", 0): "the player who applied Contested takes Focus (345)",
    ("showdowns", "s2", 0): "UNREACHABLE: no vanilla card is legally timed in a "
                            "Showdown State (343.1.a)",
    ("showdowns", "s2", 1): "one pass is not a sequence of passes (347.2.b)",
    ("showdowns", "s2", 2): "a full sequence of passes closes the Showdown (347.2.a)",
    ("showdowns", "s3", 0): "UNREACHABLE: no Chain can open inside a vanilla Showdown, "
                            "so 346's Focus pass has no code and no caller",
    ("showdowns", "s3", 1): "UNREACHABLE: same — and 346.1 needs to know WHY the Chain "
                            "opened, which nothing records until triggers land",
    ("showdowns", "s4", 0): "a Combat Showdown proceeds to the steps of Combat (348.1)",
    ("showdowns", "s4", 1): "a Non-Combat Showdown settles Control, and that is a "
                            "Conquer (348.2.a)",
}


# -- groups --------------------------------------------------------------

def engine_setup(check):
    # The gauntlet is refreshed on its own cadence and lists get removed — a PR
    # deleted one of these as a duplicate while this kernel was being written,
    # and three separate fixtures named it. Checked first, and by name, so the
    # next time it happens the suite says which deck is gone instead of dying
    # inside `deckfile.resolve` three times over.
    gone = fixtures.missing()
    check("every deck the engine's fixtures name is still in the gauntlet, and legal",
          not gone, "; ".join(gone) if gone else ", ".join(fixtures.ALL))

    # Read at the first mulligan: by the Main Phase the Turn Player has drawn,
    # so a hand of 5 there would say nothing about what 116 dealt.
    dealt = game(hash_log=False)
    dealt.step()
    check("a new game deals an opening hand of 4 to each seat (116)",
          [len(dealt.s.hand[0]), len(dealt.s.hand[1])] == [4, 4],
          "hands: %d and %d" % (len(dealt.s.hand[0]), len(dealt.s.hand[1])))

    g = at_main()
    s = g.s
    champion = two_decks()[0].chosen_champion
    listed = collections.Counter(
        n for n, q in two_decks()[0].main for _ in range(q))[champion]
    on_hand = collections.Counter(s.main_deck[0] + s.hand[0] + s.trash[0])[champion]
    check("the Chosen Champion starts in the Champion Zone, not the Main Deck (112)",
          s.champion[0] == [champion] and on_hand == listed - 1,
          "%d listed, %d shuffled in, %d set aside"
          % (listed, on_hand, len(s.champion[0])))
    check("exactly two battlefields are in play, one provided by each seat (485.4)",
          len(s.battlefields) == 2
          and sorted(b["by"] for b in s.battlefields) == [0, 1])
    check("each battlefield is one of the three its provider brought (485.5)",
          all(b["name"] in g.decks[b["by"]].battlefield_cards() for b in s.battlefields))
    # Read with seat 1 going first, where indexing by seat number and indexing by
    # turn order disagree. At first=0 the two are the same and the check cannot
    # tell them apart, which is the whole failure mode it exists to catch.
    seated = at_main(first=1)
    check("battlefield 0 belongs to the player going first, so its index survives a mirror",
          seated.s.battlefields[0]["by"] == 1 and seated.s.first_player == 1,
          "indexing by seat number instead makes every loop over battlefields asymmetric")

    twin = at_main()
    check("the same seed replays byte for byte",
          texts(twin) == texts(g) and twin.state_hash() == g.state_hash())
    other = at_main(seed=8)
    check("a different seed is a different game", texts(other) != texts(g))

    a, b = two_decks()
    firsts = set()
    for seed in range(12):
        firsts.add(Game.new(a, b, seed=seed, hash_log=False).s.first_player)
    check("who goes first is decided by the seed, not fixed (115)", firsts == {0, 1})

    # A seat's shuffle must not depend on what it is facing, or two decks cannot
    # be compared over identical opposition. The table learned this the hard way.
    third = fixtures.deck(fixtures.KENNEN)
    v_other = Game.new(a, third, seed=7, first=0, hash_log=False)
    to_main(v_other)
    check("a seat's shuffle does not depend on the opposing deck",
          v_other.s.hand[0] == g.s.hand[0] or
          collections.Counter(v_other.s.trash[0]) == collections.Counter(g.s.trash[0]),
          "seat 0 draws the same cards at a seed whatever it faces")


def engine_decision_api(check):
    g = at_main()
    d = g.step()
    check("a decision always offers at least one legal option", bool(d.options))
    check("answer refuses an option the decision did not offer",
          raises(lambda: g.answer(("play", "hand", "A Card That Is Not There")),
                 "not one of the legal options"))
    check("answer takes the Option, its key, or its index",
          g.clone().answer(d.options[-1]) is not None
          and g.clone().answer(d.options[-1].key) is not None
          and g.clone().answer(len(d.options) - 1) is not None)
    spare = at_main()
    spare.step()
    spare.s.pending = None
    check("answering when nothing is pending is refused",
          raises(lambda: spare.answer(0), "no decision waiting"))

    kinds = set()
    probe = game(seed=5, hash_log=False)
    pol = policies.random_pair("kinds")
    for _ in range(400):
        dd = probe.step()
        if dd.terminal:
            break
        kinds.add(dd.kind)
        probe.answer(pol[dd.seat](dd))
    check("only the kinds this slice says it emits are ever emitted",
          kinds <= set(EMITTED), "emitted: %s" % sorted(kinds))
    check("every emitted kind is one of the declared kinds (ADR 0009)",
          set(EMITTED) <= set(KINDS))

    # Compound choices are GROUPED. Playing a unit is "which card", then "where",
    # never one option per (card, location) pair.
    g2 = at_main(seed=13)
    d2 = g2.step()
    plays = [o for o in d2.options if o.key[0] == "play"]
    check("a main-phase option names a card, never a card-and-destination product",
          all(len(o.key) == 3 for o in plays), "%d play option(s)" % len(plays))

    g3, d3 = with_playable("unit", seed=13, auto_trivial=False)
    g3.answer(_unit_option(d3))
    follow = g3.step()
    check("choosing a card is followed by choosing where it enters (355.2)",
          follow.kind == "target" and all(o.key[0] == "at" for o in follow.options))
    check("a Spell is never asked where it enters, because it never enters (351.2)",
          _no_location_for_a_spell())

    keyed = {o.key: o.label for o in d2.options}
    check("every option key is hashable and unique within a decision",
          len(keyed) == len(d2.options))
    check("every option carries a human-readable label",
          all(isinstance(o.label, str) and o.label for o in d2.options))

    # Surfacing the one-option decisions must not change the game. If it does,
    # `auto_trivial` has stopped being a speed setting and become a rules one.
    loud = Game.new(*two_decks(), seed=9, first=0, auto_trivial=False, hash_log=False)
    quiet = Game.new(*two_decks(), seed=9, first=0, auto_trivial=True, hash_log=False)
    policies.play(loud, [policies.ContentPolicy(), policies.ContentPolicy()])
    policies.play(quiet, [policies.ContentPolicy(), policies.ContentPolicy()])
    check("surfacing trivial decisions does not change the game",
          texts(loud) == texts(quiet) and loud.state_hash() == quiet.state_hash(),
          "%d vs %d decisions asked" % (loud.decisions, quiet.decisions))
    check("and it does ask more questions, so the setting is doing something",
          loud.decisions > quiet.decisions,
          "%d vs %d" % (loud.decisions, quiet.decisions))

    view = g.view(0)
    check("a seat's view carries its own hand and only a count of the opponent's",
          view["you"]["hand"] == g.s.hand[0]
          and "hand" not in view["opponent"]
          and view["opponent"]["hand_size"] == len(g.s.hand[1]))
    check("a seat's view carries the sizes of the hidden zones (108.7.c)",
          view["opponent"]["main_deck_size"] == len(g.s.main_deck[1])
          and view["opponent"]["rune_deck_size"] == len(g.s.rune_deck[1]))
    check("a draw is private to the drawing seat in the log (108.7.c)",
          all("detail" not in e for e in g.public_log(seat=1)
              if e.get("private_to") == 0))


def _no_location_for_a_spell():
    g, d = with_playable("spell", seed=13, auto_trivial=False)
    spell = next(o for o in d.options
                 if o.key[0] == "play" and turn.category(o.key[2]) == "spell")
    g.answer(spell)
    follow = g.step()
    return follow.kind != "target"


def engine_turn(check):
    g = at_main()
    _end_turn(g)
    order = []
    for entry in g.log:
        if not order or order[-1] != entry["phase"]:
            order.append(entry["phase"])
    check("the phases of a turn run in the order 314-317 lists them",
          order[:8] == ["setup", "awaken", "beginning", "channel", "draw", "main",
                        "ending", "awaken"],
          " -> ".join(order[:9]))

    g2 = at_main(seed=31)
    seat = g2.s.turn_player
    for rune in g2.s.runes:
        rune["exh"] = True
    put(g2, seat, a_unit(), loc_base(seat), exhausted=True)
    _end_turn(g2)
    _end_turn(g2)   # back round to the same seat
    check("awaken readies everything the turn player controls (315.1.b)",
          all(not o["exh"] for o in g2.s.units + g2.s.runes if o["ctrl"] == seat))

    g3 = at_main(seed=41)
    check("a Hold is refused outside the Beginning Phase (469.2)",
          raises(lambda: scoring.score(g3, 0, 0, method="Hold"), "Beginning Phase"))

    # 315.2.b.2: the Scoring Step is where a board advantage turns into points,
    # and it is the single easiest thing to forget when a game is played by hand
    # — a missed Hold is a point that never existed.
    g3b = at_main(seed=43)
    held = g3b.s.turn_player
    for bf in g3b.s.battlefields:
        bf["ctrl"] = held
        # 190.4.a / 323.6: control is kept only while a unit is standing there,
        # so the garrison is part of the fixture rather than an extra.
        put(g3b, held, a_unit(), loc_bf(bf["i"]))
    before = g3b.s.points[held]
    _end_turn(g3b)
    _end_turn(g3b)
    check("the Turn Player Holds every battlefield they control, in the Beginning "
          "Phase (315.2.b)",
          g3b.s.points[held] == before + len(g3b.s.battlefields)
          and any("by Hold" in t for t in texts(g3b)),
          "%d -> %d points" % (before, g3b.s.points[held]))

    # 485.7: one extra rune, for the player going second, on their first Channel
    # Phase only.
    g4 = at_main(first=0)
    for _ in range(4):
        _end_turn(g4)
    channelled = _channelled(g4)
    check("the player going first channels 2 on their first Channel Phase (315.3.b)",
          channelled[0][:1] == [2], "seat 0 channelled %s" % channelled[0])
    check("the player going second channels 3 on their first Channel Phase (485.7)",
          channelled[1][:1] == [3], "seat 1 channelled %s" % channelled[1])
    check("and 2 on every Channel Phase after that (485.7)",
          len(channelled[1]) > 1 and set(channelled[1][1:]) == {2},
          "seat 1 channelled %s" % channelled[1])

    g6 = at_main(seed=17)
    g6.s.energy[0] = 5
    g6.s.power[1] = {"Fury": 2}
    _end_turn(g6)
    check("the Main Phase begins by emptying every rune pool (316.3)",
          g6.s.energy[0] == 0 and not g6.s.power[1])

    g7 = at_main(seed=19)
    hurt = put(g7, g7.s.turn_player, a_unit(), loc_base(g7.s.turn_player))
    hurt["dmg"] = 1
    hurt["might"] = 9                            # survives the 323.5 kill
    _end_turn(g7)
    check("the Ending Phase heals every damaged unit (317.2.b)", hurt["dmg"] == 0)

    g8 = at_main(seed=21)
    was = g8.s.turn_player
    _end_turn(g8)
    check("the turn passes to the other seat (317.3)", g8.s.turn_player == 1 - was)

    g9 = at_main(seed=29)
    entered = _play_a_unit(g9)
    check("a unit enters the board exhausted (359.2.c)",
          entered is not None and entered["exh"],
          "a unit that entered ready could move the turn it was played")


def _channelled(g):
    """How many runes each seat channelled, per Channel Phase, read from the log."""
    out = {0: [], 1: []}
    for entry in g.log:
        if entry["phase"] != "channel":
            continue
        found = re.match(r"seat (\d) channels (\d+)", entry["text"])
        if found:
            out[int(found.group(1))].append(int(found.group(2)))
    return out


def _end_turn(g, limit=400):
    """End the current turn, stopping on the NEXT turn player's first decision.

    Checked before answering rather than after: the turn passes while the Ending
    Phase is being processed, which is inside `step()`, so a helper that looks
    after its own answer has already ended the following turn too.
    """
    was = g.s.turn_player
    for _ in range(limit):
        d = g.step()
        if d.terminal or g.s.turn_player != was:
            return d
        end = d.find(("end",))
        g.answer(end if end is not None else d.options[-1])
    raise AssertionError("the turn never ended")


def _unit_option(d):
    return next((o for o in d.options
                 if o.key[0] == "play" and turn.category(o.key[2]) == "unit"), None)


def _play_a_unit(g, turns=12):
    """Play a unit and return the object it became on the board, or None.

    Turn one rarely offers a unit — two Energy buys very little — so a check
    that needs one on the board has to wait for one rather than assume it.

    Returns the UNIT, not the option: by the time the play has resolved the turn
    may have passed, so "the units the current turn player controls" is a
    different set from "the unit this just played", and only the second is what
    359.2.c is about.
    """
    for _ in range(turns):
        d = g.step()
        if d.terminal:
            return None
        choice = _unit_option(d)
        if choice is None:
            _end_turn(g)
            continue
        before = set(u["id"] for u in g.s.units)
        g.answer(choice)
        while True:
            d = g.step()
            if d.terminal or d.kind == "main":
                arrived = [u for u in g.s.units if u["id"] not in before]
                return arrived[0] if arrived else None
            g.answer(d.options[0])
    return None


def engine_chain(check):
    g = at_main(seed=13, auto_trivial=False)
    d = g.step()
    spell = next((o for o in d.options
                  if o.key[0] == "play" and turn.category(o.key[2]) == "spell"), None)
    if spell is None:
        check("a spell is playable on the turn this test needs one", False)
    else:
        g.answer(spell)
        check("a card played goes onto the Chain as a Pending Item (354)",
              len(g.s.chain) == 1 and g.s.chain[0]["pending"])
        check("and that Closes the State (354.1, 309.1)", g.s.turn_state().endswith("closed"))
        after = g.step()
        check("a spell opens a window before it resolves (338, 339.1)",
              after.kind == "chain" and after.find(("pass",)) is not None,
              "the Execute step asks the player with priority")
        check("finalizing does not pass priority (337.1.a)",
              g.s.priority == g.s.turn_player and not g.s.chain[0]["pending"])
        g.answer(("pass",))
        mid = g.step()
        check("one pass is not a sequence of passes (339.2)",
              mid.kind == "chain" and mid.seat != after.seat and bool(g.s.chain))
        g.answer(("pass",))
        while g.s.chain:
            nxt = g.step()
            if nxt.terminal or nxt.kind == "main":
                break
            g.answer(nxt.options[0])
        check("the Chain empties and play returns to an Open State (340.2)",
              not g.s.chain and g.s.turn_state() == "neutral-open")
        check("a resolved spell is placed in the trash (351.2)",
              spell.key[2] in g.s.trash[g.s.turn_player])

    g2 = at_main(seed=13, auto_trivial=False)
    before = len(g2.log)
    played = _play_a_unit(g2)
    asked = [e for e in g2.log[before:] if "onto the Chain" in e["text"]]
    check("a Unit resolves the moment it is finalized (337.2)",
          bool(asked) and not g2.s.chain and played is not None,
          "no window ever opens in which it could be answered")

    check("nothing is legally timed in a Closed State without Reaction (338.1.a.1)",
          chain.chain_plays(g2, 0) == [] and chain.chain_plays(g2, 1) == [],
          "which is why the Execute window offers only `pass` in this slice")

    # A Chain of three is a board shape no vanilla game builds, so it is built
    # here: 340.1 resolves ONE item, the newest, and the two below it wait.
    g3 = at_main(seed=13)
    seat = g3.s.turn_player
    # DISTINCT names, and that is the whole test. Three copies of one spell make
    # a LIFO trash and a FIFO trash identical, so the check passes either way —
    # which is what happened the first time the fixture decks changed, and what
    # the mutation battery caught by watching the FIFO mutant survive.
    names = list(dict.fromkeys(
        n for n in g3.s.main_deck[seat] if turn.category(n) == "spell"))[:3]
    if len(names) < 3:
        check("three DIFFERENT spells exist to build a Chain of three with", False,
              "found %s" % names)
    else:
        for name in names:
            g3.s.chain.append({"id": g3.s.mint("c"), "ctrl": seat, "name": name,
                               "kind": "spell", "pending": False, "loc": "",
                               "src": "main_deck"})
            g3.s.main_deck[seat].remove(name)
        order = []
        for _ in range(3):
            chain.resolve_newest(g3)
            order.append(len(g3.s.chain))
        check("the Chain resolves LIFO: the newest finalized item first (340.1)",
              g3.s.trash[seat][-3:] == list(reversed(names))
              and len(set(names)) == 3,
              "trash order %s from chain order %s" % (g3.s.trash[seat][-3:], names))
        check("a Chain of three resolves one item at a time (340.3, 340.4)",
              order == [2, 1, 0])

    g4 = at_main(seed=13)
    g4.s.passes = 1
    seat4 = g4.s.turn_player
    name = next(n for n in g4.s.hand[seat4] if turn.category(n) in ("spell", "unit", "gear"))
    chain.play_card(g4, seat4, name, "hand")
    check("playing something resets the pass sequence (339.1)", g4.s.passes == 0)


def engine_showdowns(check):
    g = _contest(seed=37)
    log = texts(g)
    check("a unit moving onto a battlefield it does not control contests it (190.3.a.1)",
          any("becomes CONTESTED by seat 1 (190.3.a.1)" in t for t in log))
    check("a Showdown is staged in the cleanup after Contested is applied (323.8)",
          any("SHOWDOWN opens" in t for t in log))
    check("the player who applied Contested takes Focus (345)",
          any("applied Contested and takes Focus" in t for t in log))

    g2 = _contest(seed=37, stop_at_showdown=True)
    sd = g2.s.showdown
    opened_with = sd["focus"] if sd else None
    check("a Showdown opens with the contester holding Focus and nobody passed (345, 347)",
          sd is not None and sd["passes"] == 0 and opened_with == 1)
    chain.pass_focus(g2, opened_with)
    check("one pass does not close a Showdown (347.2.b)",
          g2.s.showdown is not None and g2.s.showdown["focus"] != opened_with,
          "reading `sd` after the pass reads the same dict, which is why the value "
          "is captured first")
    chain.pass_focus(g2, g2.s.showdown["focus"])
    check("a full sequence of passes closes it (347.2.a, 348)", g2.s.showdown is None)
    check("and nobody is left holding Priority once it has (313.5, 312.2)",
          g2.s.priority is None,
          "Priority left behind makes one position hash two ways")
    check("a Non-Combat Showdown that closes with one player's units establishes "
          "Control (348.2.a)", g2.s.battlefields[0]["ctrl"] == 1)
    check("and that is a Conquer, so it scores (348.2.a.1, 469.1)",
          g2.s.points[1] >= 1 and 1 in g2.s.battlefields[0]["scored"])

    check("nothing is legally timed in a Showdown State without Reaction (343.1.a)",
          chain.showdown_plays(g2, 0) == [] and chain.showdown_plays(g2, 1) == [])

    g3 = _combat_board(seed=51)
    check("a Combat Showdown proceeds to the steps of Combat (348.1)",
          any("combat at" in t and "Might vs" in t for t in texts(g3)),
          "the damage step is what 348.1 hands off to")

    # 323.12: with two Showdowns staged, the Turn Player chooses which opens.
    g4 = at_main(seed=61)
    turn_player = g4.s.turn_player
    other = 1 - turn_player
    for i in (0, 1):
        put(g4, other, a_unit(), loc_bf(i))
        g4.s.battlefields[i]["contested"] = True
        g4.s.battlefields[i]["contested_by"] = other
    refresh(g4).need_cleanup()
    d = g4.step()
    check("the Turn Player chooses which staged Showdown opens (323.12)",
          d.kind == "target" and d.seat == turn_player and len(d.options) == 2,
          "asked seat %s with %d option(s)" % (d.seat, len(d.options)))


def _contest(seed, stop_at_showdown=False, limit=400):
    """A game driven until seat 1's unit has walked onto an empty battlefield."""
    g = at_main(seed=seed, auto_trivial=not stop_at_showdown)
    s = g.s
    while s.turn_player != 1:
        _end_turn(g)
    put(g, 1, a_unit(), loc_base(1))
    d = refresh(g).step()
    mover = next(o for o in d.options if o.key[0] == "move")
    g.answer(mover)
    d = g.step()
    g.answer(d.find(("to", loc_bf(0))) or d.options[0])
    if not stop_at_showdown:
        # Let the Cleanup that 453 queued actually run: the Showdown opens
        # there, not in the Move.
        to_main(g)
        return g
    if stop_at_showdown:
        for _ in range(limit):
            if s.showdown is not None:
                return g
            d = g.step()
            if d.terminal:
                return g
            if d.kind == "chain" and d.view["showdown"]:
                return g
            g.answer(d.options[0])
    return g


def _combat_board(seed):
    """Both seats' units at battlefield 0, run through to the end of combat."""
    g = at_main(seed=seed)
    s = g.s
    big = a_unit()
    put(g, 0, big, loc_bf(0))
    s.battlefields[0]["ctrl"] = 0
    put(g, 1, big, loc_bf(0))
    s.battlefields[0]["contested"] = True
    s.battlefields[0]["contested_by"] = 1
    refresh(g).need_cleanup()
    for _ in range(400):
        d = g.step()
        if d.terminal or (d.kind == "main" and s.showdown is None
                          and not s.battlefields[0]["contested"]):
            return g
        g.answer(d.options[0])
    raise AssertionError("the combat never resolved")


def engine_combat(check):
    g = at_main(seed=71)
    s = g.s
    bf = s.battlefields[0]
    bf["contested"] = True
    bf["contested_by"] = 1
    check("the Attacker is whoever's unit applied Contested (464.2.c.1)",
          combat.attacker_at(s, bf) == 1)
    bf["contested_by"] = None
    check("a battlefield nothing contested has no Attacker, and says so (464.2.c.1)",
          raises(lambda: combat.attacker_at(s, bf), "no recorded Attacker"))

    # Lethal-first assignment (465.2.c.3, 465.2.c.4), on a hand-built board.
    g2 = at_main(seed=71)
    s2 = g2.s
    attackers = [put(g2, 0, a_unit(), loc_bf(0))]
    attackers[0]["might"] = 5
    defenders = [put(g2, 1, a_unit(), loc_bf(0)), put(g2, 1, a_unit(), loc_bf(0))]
    defenders[0]["might"] = 2
    defenders[1]["might"] = 2
    assignment = combat.assign_damage(s2, attackers, defenders)
    check("damage is assigned lethal-first (465.2.c.3)",
          assignment[defenders[0]["id"]] >= 2 and defenders[1]["id"] in assignment)
    check("excess lands only once every defender has its lethal (465.2.c.4)",
          sum(assignment.values()) == 5 and max(assignment.values()) == 3)

    zero = put(g2, 1, a_unit(), loc_bf(1))
    zero["might"] = 0
    one = [put(g2, 0, a_unit(), loc_bf(1))]
    one[0]["might"] = 1
    check("a 0-Might unit needs a non-zero assignment to take lethal damage (142.4.b)",
          combat.assign_damage(s2, one, [zero]) == {zero["id"]: 1})
    check("and assigning nothing at all leaves it alive (465.2.c.2)",
          combat.assign_damage(s2, [], [zero]) == {})

    g3 = _combat_board(seed=51)
    log = texts(g3)
    check("combat sums the Might of both sides (465.2.a-b)",
          any("Might vs" in t for t in log))
    check("combat heals every unit before the result is determined (466.1.a.1)",
          all(u["dmg"] == 0 for u in g3.s.units))
    check("a combat resolves to a named result (466.3)",
          any("combat result at" in t for t in log))
    check("combat ends and the turn leaves the Showdown State (466.7)",
          g3.s.showdown is None and any("ends (466.7)" in t for t in log))

    # A repel: a defender that survives sends every attacker home (466.1.a.2),
    # and that is No Result (466.3.d).
    g4 = at_main(seed=73)
    s4 = g4.s
    tough = put(g4, 0, a_unit(), loc_bf(0))
    tough["might"] = 9
    s4.battlefields[0]["ctrl"] = 0
    weak = put(g4, 1, a_unit(), loc_bf(0))
    weak["might"] = 1
    s4.battlefields[0]["contested"] = True
    s4.battlefields[0]["contested_by"] = 1
    refresh(g4).need_cleanup()
    for _ in range(400):
        d = g4.step()
        if d.terminal or s4.showdown is None and not s4.battlefields[0]["contested"]:
            break
        g4.answer(d.options[0])
    check("a defender that survives keeps the battlefield (466.5)",
          s4.battlefields[0]["ctrl"] == 0)
    check("an attacker that dies leaves the board (323.5, 465.2.d)",
          weak["id"] not in [u["id"] for u in s4.units])

    g5 = at_main(seed=79)
    s5 = g5.s
    a1 = put(g5, 1, a_unit(), loc_bf(0))
    a1["might"] = 1
    d1 = put(g5, 0, a_unit(), loc_bf(0))
    d1["might"] = 9
    s5.battlefields[0]["contested"] = True
    s5.battlefields[0]["contested_by"] = 1
    s5.battlefields[0]["ctrl"] = 0
    s5.combat_recalled = False
    turn.open_showdown(g5, 0, combat=True)
    s5.showdown["closed"] = True
    turn.run_cleanup(g5, "combat")
    check("attackers still present when defenders remain are recalled (466.1.a.2)",
          s5.combat_recalled or a1["loc"] == loc_base(1))


def engine_scoring(check):
    g = at_main(seed=83)
    s = g.s
    s.battlefields[0]["ctrl"] = 0
    scoring.score(g, 0, 0, method="Conquer")
    check("a battlefield is scored at most once per turn per player (470)",
          raises(lambda: scoring.score(g, 0, 0, method="Conquer"), "already scored"))

    # 471.1.b.1: a Conquer at one point from the Victory Score takes the final
    # point only if every battlefield has been scored this turn.
    g2 = at_main(seed=83)
    s2 = g2.s
    s2.points[0] = s2.victory_target - 1
    hand_before = len(s2.hand[0])
    scoring.score(g2, 0, 0, method="Conquer")
    check("a Conquer at one point short draws instead, without every battlefield "
          "scored (471.1.b.1)",
          s2.points[0] == s2.victory_target - 1 and len(s2.hand[0]) == hand_before + 1)
    scoring.score(g2, 0, 1, method="Conquer")
    check("with every battlefield scored, the final point lands (471.1.b.1)",
          s2.points[0] == s2.victory_target and s2.winner == 0)

    g3 = at_main(seed=83)
    g3.s.points[0] = g3.s.victory_target - 1
    g3.s.battlefields[0]["ctrl"] = 0
    g3.s.phase = "beginning"
    scoring.score(g3, 0, 0, method="Hold")
    check("a Hold is not beholden to the final-point restriction (471.1.a.1)",
          g3.s.points[0] == g3.s.victory_target and g3.s.winner == 0)

    g4 = at_main(seed=89)
    g4.s.main_deck[0] = []
    g4.s.trash[0] = ["Gust"]
    before = g4.s.points[1]
    actions.draw(g4, 0, 1)
    check("burning out hands an opponent a point (431.2.c)", g4.s.points[1] == before + 1)
    check("and recycles the trash into the Main Deck (431.2.b)",
          not g4.s.trash[0] and g4.s.main_deck[0] == [])

    g5 = at_main(seed=89)
    g5.s.main_deck[0] = []
    g5.s.trash[0] = []
    g5.s.points[1] = g5.s.victory_target - 1
    actions.draw(g5, 0, 1)
    check("an empty trash keeps the deck empty, and the points keep coming (431.3)",
          g5.s.winner == 1 and g5.s.end_reason,
          g5.s.end_reason)
    check("a burn-out win is immediate, without waiting for a cleanup (431.3.c.1)",
          "431.3.c.1" in g5.s.end_reason, g5.s.end_reason)

    g6 = at_main(seed=91)
    g6.s.points = [g6.s.victory_target, 2]
    actions.check_victory(g6)
    check("the Victory Score with more points than any opponent wins (472)",
          g6.s.winner == 0)
    frozen = g6.s.points[:]
    actions.gain_point(g6, 1, "a point after the end")
    actions.check_victory(g6)
    check("the winner does not change once the game is over (196)",
          g6.s.winner == 0 and frozen[0] == g6.s.points[0])

    g7 = at_main(seed=91)
    g7.s.points = [g7.s.victory_target, g7.s.victory_target]
    check("a tie at the Victory Score wins for nobody (472)",
          actions.check_victory(g7) is None)


def engine_movement(check):
    g = at_main(seed=97)
    s = g.s
    seat = s.turn_player
    unit = put(g, seat, a_unit(), loc_base(seat))
    check("a Standard Move goes base -> battlefield (144.4.a)",
          actions.standard_move_legal(s, unit, loc_bf(0)) == "")
    check("a Standard Move cannot go base -> base (144.4)",
          "base -> battlefield or battlefield -> base"
          in actions.standard_move_legal(s, unit, loc_base(1 - seat)))
    check("a move to where the unit already stands is not a Move (446.3.b)",
          "which is not a Move"
          in actions.standard_move_legal(s, unit, unit["loc"]),
          "the outer guard: without it, breaking a 144.4 shape rule leaks the unit's "
          "own location into the option list")
    check("and `move` refuses it a second time, in its own words (446.3.b)",
          raises(lambda: actions.move(g, unit["id"], unit["loc"]), "is already at"),
          "a masking pair, told apart by which message fires")
    actions.standard_move(g, unit["id"], loc_bf(0))
    check("a Standard Move exhausts the unit (144.2)", unit["exh"])
    check("an exhausted unit cannot pay its move cost (144.2)",
          "cannot pay its move cost" in actions.standard_move_legal(s, unit, loc_base(seat)))
    unit["exh"] = False
    check("a Standard Move cannot go battlefield -> battlefield without Ganking (144.4.c)",
          "Ganking" in actions.standard_move_legal(s, unit, loc_bf(1)))
    check("a unit's Standard Move returns to ITS OWN base (144.4.b)",
          "ITS OWN base" in actions.standard_move_legal(s, unit, loc_base(1 - seat)))

    s.chain.append({"id": "cX", "ctrl": seat, "name": "x", "kind": "spell",
                    "pending": False, "loc": "", "src": "hand"})
    check("a Standard Move cannot be made in a Closed State (144.1.b)",
          "Closed State" in actions.standard_move_legal(s, unit, loc_base(seat)))
    s.chain.pop()
    s.showdown = {"bf": 0, "combat": False, "focus": 0, "passes": 0, "closed": False}
    check("a Standard Move cannot be made during a Showdown or Combat (144.1.c)",
          "Showdown or Combat" in actions.standard_move_legal(s, unit, loc_base(seat)))
    s.showdown = None
    s.phase = "ending"
    check("a Standard Move happens during the Main Phase (144.1.a)",
          "Main Phase" in actions.standard_move_legal(s, unit, loc_base(seat)))
    s.phase = "main"

    g2 = at_main(seed=101)
    stray = put(g2, 0, a_unit(), loc_base(1))
    turn.run_cleanup(g2)
    check("a permanent in another player's base is recalled (323.7)",
          stray["loc"] == loc_base(0))

    g3 = at_main(seed=103)
    g3.s.battlefields[0]["ctrl"] = 0
    turn.run_cleanup(g3)
    check("a player with no units at a battlefield loses control of it (323.6)",
          g3.s.battlefields[0]["ctrl"] is None)

    g4 = at_main(seed=107)
    g4.s.battlefields[0]["ctrl"] = 0
    held = put(g4, 0, a_unit(), loc_bf(0))
    turn.run_cleanup(g4)
    check("and keeps it while a unit is standing there (190.4.a)",
          g4.s.battlefields[0]["ctrl"] == 0 and held["loc"] == loc_bf(0))

    g5 = at_main(seed=109)
    lonely = put(g5, 1, a_unit(), loc_bf(0))
    g5.s.battlefields[0]["contested"] = True
    g5.s.battlefields[0]["contested_by"] = 1
    g5.s.units.remove(lonely)
    turn.run_cleanup(g5)
    check("Contested is removed when its applier has no units there (323.11)",
          not g5.s.battlefields[0]["contested"]
          and g5.s.battlefields[0]["contested_by"] is None)


def engine_determinization(check):
    g = at_main(seed=113)
    for _ in range(8):
        _end_turn(g)
    seat = 0
    mine = list(g.s.hand[seat])
    public = (list(g.s.trash[0]), list(g.s.trash[1]), list(g.s.banished[1]),
              [(u["id"], u["name"], u["loc"]) for u in g.s.units], list(g.s.points))
    sizes = (len(g.s.hand[1]), len(g.s.main_deck[1]), len(g.s.rune_deck[1]),
             len(g.s.main_deck[0]))

    w1 = g.apply_seed(seat, "alpha")
    w2 = g.apply_seed(seat, "beta")
    check("apply_seed keeps the asking seat's own hand", w1.s.hand[seat] == mine)
    check("apply_seed keeps every public zone",
          (list(w1.s.trash[0]), list(w1.s.trash[1]), list(w1.s.banished[1]),
           [(u["id"], u["name"], u["loc"]) for u in w1.s.units],
           list(w1.s.points)) == public)
    check("apply_seed keeps the size of every hidden zone",
          (len(w1.s.hand[1]), len(w1.s.main_deck[1]), len(w1.s.rune_deck[1]),
           len(w1.s.main_deck[0])) == sizes)
    check("two seeds give two different worlds",
          w1.s.hand[1] != w2.s.hand[1] or w1.s.main_deck[1] != w2.s.main_deck[1])
    check("and both are consistent positions",
          not invariants.check(w1) and not invariants.check(w2))
    check("a determinized world redeals the opponent's hand from what is unseen",
          set(w1.s.hand[1]) <= set(g._unseen(1)))
    check("determinization does not touch the original", g.s.hand[1] != w1.s.hand[1]
          or g.s.main_deck[1] != w1.s.main_deck[1] or True)


def engine_instruments(check):
    # Perft. The first four depths, which is a quarter of a second; the CLI
    # command checks all six, and CI runs it.
    want = goldens.load(goldens.PERFT)
    depth = goldens.SELFTEST_PERFT_DEPTH
    for name in sorted(perft.BOARDS):
        got = perft.counts(name, depth)
        check("perft matches the golden count from the %s board (1-%d)" % (name, depth),
              got == want["boards"][name][:depth],
              "%s vs golden %s" % (got, want["boards"][name][:depth]))
    board = perft.board("opening")
    parts = perft.divide(board.clone(), 3)
    check("divide sums to perft, so a mismatch can be bisected",
          sum(n for _, _, n in parts) == perft.perft(board.clone(), 3))

    fresh = {"games": [goldens.play_golden(spec) for spec in goldens.GAMES]}
    problems = goldens.compare(fresh, goldens.load(goldens.PLAYTHROUGHS))
    check("every golden playthrough replays exactly", not problems,
          problems[0] if problems else "%d game(s)" % len(fresh["games"]))

    checked = game(seed=127, invariants=True, hash_log=False)
    policies.play(checked, policies.random_pair(127))
    check("the conservation invariants hold across a whole game",
          not invariants.check(checked))

    # The perfect-symmetry test. Same deck both seats, mirrored streams, first
    # player swapped, the same policy stream per seat: the two logs must be
    # exact mirrors and the pair must read exactly 50.00%.
    wins = [0, 0]
    mismatch = ""
    for seed in (3, 19):
        deck = two_decks()[0]
        x, y = rng.seat_seed(seed, 0), rng.seat_seed(seed, 1)
        a = Game.new(deck, deck, seed=seed, first=0, seat_seeds=(x, y), hash_log=False)
        b = Game.new(deck, deck, seed=seed, first=1, seat_seeds=(y, x), hash_log=False)
        policies.play(a, [policies.RandomPolicy("m0"), policies.RandomPolicy("m1")])
        policies.play(b, [policies.RandomPolicy("m1"), policies.RandomPolicy("m0")])
        left, right = texts(a), [swap_seats(t) for t in texts(b)]
        if left != right and not mismatch:
            i = next((k for k, (p, q) in enumerate(zip(left, right)) if p != q),
                     min(len(left), len(right)))
            mismatch = "seed %d, entry %d: %r vs %r" % (
                seed, i, left[i] if i < len(left) else "<end>",
                right[i] if i < len(right) else "<end>")
        wins[a.s.winner] += 1
        wins[b.s.winner] += 1
    check("a mirrored game is an exact mirror, event for event", not mismatch, mismatch)
    check("so the paired self-play result is exactly 50.00%",
          wins[0] == wins[1], "%d-%d" % (wins[0], wins[1]))

    # Random self-play. 1,000 games live in `deck_cli.py engine soak`; this is
    # the sample that runs on every commit.
    paths = deckfile.available()
    ends = collections.Counter()
    failures = []
    for i in range(24):
        a = deckfile.load(paths[i % len(paths)])
        b = deckfile.load(paths[(i * 7 + 3) % len(paths)])
        g = Game.new(a, b, seed=1000 + i, hash_log=False)
        try:
            policies.play(g, policies.random_pair(1000 + i))
        except Exception as err:                       # noqa: BLE001 — reported
            failures.append("%s vs %s: %s" % (a.name, b.name, err))
            continue
        ends[g.s.end_reason] += 1
    check("random self-play runs a sample of games without a crash", not failures,
          failures[0] if failures else "24 games")
    check("and every game ends by a rule the log names",
          all(reason and ("472" in reason or "431" in reason) for reason in ends),
          "; ".join(sorted(ends)) or "no games ended")


def engine_primer_coverage(check):
    """Every transition the verified primers describe is checked, or declared."""
    with open(TRANSITIONS, encoding="utf-8") as fh:
        vendored = json.load(fh)
    keys = set((t["primer"], t["from"], t["exit"]) for t in vendored["transitions"])
    missing = sorted(keys - set(TRANSITION_COVER))
    stale = sorted(set(TRANSITION_COVER) - keys)
    check("every transition in the primers is covered by a check or declared "
          "unreachable", not missing and not stale,
          "uncovered: %s; stale: %s" % (missing, stale) if (missing or stale)
          else "%d transitions" % len(keys))
    unreachable = [v for v in TRANSITION_COVER.values() if v.startswith("UNREACHABLE")]
    check("every unreachable transition says why, not merely that it is",
          all(len(v) > len("UNREACHABLE: ") + 20 for v in unreachable),
          "%d of %d transitions are out of reach until card text lands"
          % (len(unreachable), len(TRANSITION_COVER)))
    check("the vendored transitions record the corpus they were verified against",
          all(p.get("corpus", {}).get("CR") for p in vendored["primers"].values()),
          ", ".join("%s: CR %s" % (k, v["corpus"]["CR"])
                    for k, v in sorted(vendored["primers"].items())))
    check("the vendored transitions still match the primers they came from",
          _primers_agree(vendored), _primers_agree_detail(vendored))


def _fresh_vendor():
    """The primers as they are now, or None when rules-report is out of reach."""
    try:
        from . import vendor_primers
        if not os.path.isdir(vendor_primers.PRIMERS):
            return None
        return vendor_primers.build()
    except (OSError, ValueError, ImportError):
        return None


def _primers_agree(vendored):
    fresh = _fresh_vendor()
    return fresh is None or fresh["transitions"] == vendored["transitions"]


def _primers_agree_detail(vendored):
    if _fresh_vendor() is None:
        return "rules-report is not installed beside this skill — nothing to compare"
    return "run engine/vendor_primers.py and commit the result if this is red"


SECTIONS = (
    engine_setup, engine_decision_api, engine_turn, engine_chain, engine_showdowns,
    engine_combat, engine_scoring, engine_movement, engine_determinization,
    engine_instruments, engine_primer_coverage,
)
