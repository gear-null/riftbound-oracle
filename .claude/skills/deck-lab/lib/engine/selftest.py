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
import sys

import cards
import deckfile
import table

from . import (actions, chain, combat, fixtures, goldens, invariants, parity,
               perft, policies, ported, rng, scoring, turn)
from .decisions import EMITTED
from .game import Game
from .state import RulesError, loc_base, loc_bf, new_rune, new_unit

HERE = os.path.dirname(os.path.abspath(__file__))
TRANSITIONS = os.path.join(HERE, "goldens", "chain-transitions.json")

#: The names the TABLE's half of the suite registered, captured before the
#: engine's sections start appending to the same list. `engine_ported` needs to
#: tell the two halves apart, and the registry is one flat list of names.
TABLE_NAMES = []


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
#: Every value is either the EXACT name of a check that runs, or a reason
#: beginning "UNREACHABLE:". `engine_primer_coverage` resolves the first kind
#: against the names the suite actually registered — prose here was a claim
#: nobody verified, and four entries named checks that did not exist.
TRANSITION_COVER = {
    ("combat", "s1", 0): "a Combat opens at a cleanup, at a battlefield the Turn "
                         "Player chooses (323.13)",
    ("combat", "s1", 1): "a Combat that stops being staged before it opens is not "
                         "resolved (461.2, 323.10)",
    ("combat", "s2", 0): "combat sums the Might of both sides (465.2.a-b)",
    ("combat", "s2", 1): "a combat with one side gone skips the Damage Step (465.1)",
    ("combat", "s3", 0): "the Damage Step cancels the Tasks the Showdown left "
                         "outstanding (465.3)",
    ("combat", "s4", 0): "UNREACHABLE: 466.3.d.1 needs BOTH players to still have "
                         "units here after the Combat Cleanup, and 466.1.a.2 has "
                         "just recalled every Attacker if any Defender survived. "
                         "Only an effect that prevents the recall reaches it, and "
                         "that is card text",
    ("combat", "s4", 1): "combat ends by removing the designation from every unit "
                         "and player (466.7.a)",
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
    ("hot-fepr", "s5", 2): "three items resolve newest first, one at a time (340.4)",
    ("showdowns", "s1", 0): "the player who applied Contested takes Focus (345)",
    ("showdowns", "s2", 0): "UNREACHABLE: no vanilla card is legally timed in a "
                            "Showdown State (343.1.a)",
    ("showdowns", "s2", 1): "one pass is not a sequence of passes (347.2.b)",
    ("showdowns", "s2", 2): "a full sequence of passes closes the Showdown (347.2.a, 348)",
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
    # The first engine section, so this is the moment the registry holds the
    # table's checks and none of the engine's.
    if not TABLE_NAMES:
        TABLE_NAMES.extend(_registered_names() or [])

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

    # The two seats must draw from DIFFERENT streams at the same seed, or a
    # mirror match deals both players the same cards. The perfect-symmetry test
    # cannot see this: it passes its seat seeds in explicitly.
    same = Game.new(fixtures.deck(fixtures.IRELIA), fixtures.deck(fixtures.IRELIA),
                    seed=7, first=0, hash_log=False)
    same.step()
    check("the two seats draw from different streams at the same seed",
          same.s.hand[0] != same.s.hand[1] and rng.seat_seed(7, 0) != rng.seat_seed(7, 1),
          "the same deck on both seats must not deal the same opening hand")

    # A seat's shuffle must not depend on what it is facing, or two decks cannot
    # be compared over identical opposition. The table learned this the hard way.
    third = fixtures.deck(fixtures.KENNEN)
    v_other = Game.new(a, third, seed=7, first=0, hash_log=False)
    to_main(v_other)
    check("a seat's shuffle does not depend on the opposing deck",
          v_other.s.hand[0] == g.s.hand[0] or
          collections.Counter(v_other.s.trash[0]) == collections.Counter(g.s.trash[0]),
          "seat 0 draws the same cards at a seed whatever it faces")


def engine_cloning(check):
    """`clone()` is what search spends its time on. It has to be a real copy."""
    g = at_main(seed=13, auto_trivial=False)
    d = g.step()
    before_options = list(g.s.pending["options"])
    clone = g.clone()
    clone.s.pending["options"].append((("BOGUS",), "an option nobody generated"))
    check("mutating a clone's decision options does not add an option to the "
          "original's decision",
          g.s.pending["options"] == before_options
          and g.step().find(("BOGUS",)) is None,
          "a shallow-copied `pending` hands the real game an illegal move")

    # Every other mutable thing reachable from the state, in one sweep.
    g2 = at_main(seed=17)
    seat = g2.s.turn_player
    put(g2, seat, a_unit(), loc_base(seat))
    g2.s.chain.append({"id": "cZ", "ctrl": seat, "name": "x", "kind": "spell",
                       "pending": False, "loc": "", "src": "hand"})
    g2.s.choosing = {"what": "mulligan", "seat": seat, "aside": ["one"]}
    g2.s.showdown = {"bf": 0, "combat": False, "focus": 0, "passes": 0, "closed": False}
    g2.s.battlefields[0]["scored"] = [seat]
    g2.s.power[seat] = {"Fury": 1}
    fingerprint = g2.state_hash()
    log_length = len(g2.log)

    c2 = g2.clone()
    c2.s.hand[0].append("GHOST")
    c2.s.main_deck[1].clear()
    c2.s.trash[0].append("GHOST")
    c2.s.banished[1].append("GHOST")
    c2.s.champion[0].clear()
    c2.s.chain[0]["name"] = "MUTATED"
    c2.s.chain.append(dict(c2.s.chain[0]))
    c2.s.units[0]["loc"] = "bf:1"
    c2.s.runes and c2.s.runes[0].update(exh=True)
    c2.s.battlefields[0]["scored"].append(1 - seat)
    c2.s.battlefields[0]["ctrl"] = 1 - seat
    c2.s.choosing["aside"].append("two")
    c2.s.showdown["passes"] = 99
    c2.s.tasks.append(("cleanup", "ending"))
    c2.s.power[seat]["Fury"] = 99
    c2.s.points[0] += 5
    c2.log.append({"turn": 0, "phase": "x", "text": "a line the original never wrote"})

    check("a clone shares no zone, object, chain item, task or log with the original",
          g2.state_hash() == fingerprint and len(g2.log) == log_length,
          "hash %s, %d log entries" % (g2.state_hash()[:8], len(g2.log)))
    check("and the clone really did change, so the check is comparing something",
          c2.state_hash() != fingerprint and len(c2.log) == log_length + 1)


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
    done = game(seed=9, hash_log=False)
    policies.play(done, policies.random_pair(9))
    ended = done.step()
    # Written to survive its own mutant: reading `view["seats"]` directly makes
    # this KeyError rather than fail when the terminal view goes back to being a
    # seat's, and a check that dies takes the suite with it and reports nothing.
    sides = ended.view.get("seats") or [ended.view.get("you") or {}]
    check("the terminal decision carries no hand, because it belongs to no seat "
          "(108.7.c)",
          ended.terminal and ended.seat is None
          and not any(side.get("hand") for side in sides),
          "built from seat 0's view, it hands seat 0's cards to whoever finishes "
          "the game")

    check("a draw is private to the drawing seat in the log (108.7.c)",
          all("detail" not in e for e in g.public_log(seat=1)
              if e.get("private_to") == 0))


def _a_chain_window():
    """A game stopped on the Execute step of a Chain a spell opened (338)."""
    g, d = with_playable("spell", seed=13, auto_trivial=False)
    spell = next(o for o in d.options
                 if o.key[0] == "play" and turn.category(o.key[2]) == "spell")
    g.answer(spell)
    for _ in range(20):
        nxt = g.step()
        if nxt.terminal:
            return g, None
        if nxt.kind == "chain":
            return g, nxt
        g.answer(nxt.options[0])
    return g, None


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

    # Asserted on a window the engine actually opened, not on the generator's
    # return value: `chain_plays(...) == []` is a predicate over a literal and
    # passes whatever the Execute step does with it.
    g_open, d_open = _a_chain_window()
    check("the Execute window a played spell opens offers exactly `pass` (338.1.a.1)",
          d_open is not None and [o.key for o in d_open.options] == [("pass",)],
          "a Closed State admits only Reaction, and this slice reads no keywords")

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
        check("three items resolve newest first, one at a time (340.4)",
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
    check("one pass is not a sequence of passes (347.2.b)",
          g2.s.showdown is not None and g2.s.showdown["focus"] != opened_with,
          "reading `sd` after the pass reads the same dict, which is why the value "
          "is captured first")
    chain.pass_focus(g2, g2.s.showdown["focus"])
    check("a full sequence of passes closes the Showdown (347.2.a, 348)",
          g2.s.showdown is None)
    check("and nobody is left holding Priority once it has (313.5, 312.2)",
          g2.s.priority is None,
          "Priority left behind makes one position hash two ways")
    check("a Non-Combat Showdown settles Control, and that is a Conquer (348.2.a)",
          g2.s.battlefields[0]["ctrl"] == 1
          and g2.s.points[1] >= 1 and 1 in g2.s.battlefields[0]["scored"],
          "control to seat 1, scored %s, %d point(s)"
          % (g2.s.battlefields[0]["scored"], g2.s.points[1]))

    g_sd = _contest(seed=37, stop_at_showdown=True)
    d_sd = g_sd.step()
    check("the Showdown window offers exactly `pass` (343.1.a, 347)",
          d_sd.kind == "chain" and [o.key for o in d_sd.options] == [("pass",)],
          "asserted on the window the engine opened, not on the generator")

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

    # 323.12 is task 9 and 323.13 is task 10, and the numbering decides the
    # game: both need a Neutral Open State and opening either one leaves it, so
    # with a Showdown staged at one battlefield and a Combat at another, the
    # Showdown opens and the Combat waits for a later cleanup. Taking the
    # Combat first reads as the more urgent thing and is the wrong fight.
    g5 = at_main(seed=61)
    tp = g5.s.turn_player
    other5 = 1 - tp
    put(g5, other5, a_unit(), loc_bf(0))                      # contested, alone
    g5.s.battlefields[0]["contested"] = True
    g5.s.battlefields[0]["contested_by"] = other5
    put(g5, other5, a_unit(), loc_bf(1))                      # both present
    put(g5, tp, a_unit(), loc_bf(1))
    g5.s.battlefields[1]["contested"] = True
    g5.s.battlefields[1]["contested_by"] = other5
    mark = len(g5.log)
    refresh(g5).need_cleanup()
    g5.step()
    opened = [t["text"] for t in g5.log[mark:]
              if "SHOWDOWN opens" in t["text"] or "COMBAT opens" in t["text"]]
    check("a staged Showdown opens before a staged Combat elsewhere (323.12 before "
          "323.13)",
          bool(opened) and "SHOWDOWN opens at %s" % g5.s.battlefields[0]["name"]
          in opened[0],
          opened[0][:80] if opened else "nothing opened at all")


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
    # The whole assignment, not "the first one got at least its lethal". The
    # weaker form is true of almost any wrong answer: one point at a time in
    # rotation still ends with both units on 2, and a whole pool dumped on the
    # first still leaves it above its lethal. 5 Might onto two 2-Might units has
    # exactly one lethal-first shape.
    check("damage is assigned lethal-first (465.2.c.3)",
          assignment == {defenders[0]["id"]: 2, defenders[1]["id"]: 3},
          "%r" % (assignment,))
    check("excess lands only once every defender has its lethal (465.2.c.4)",
          sum(assignment.values()) == 5 and max(assignment.values()) == 3)

    zero = put(g2, 1, a_unit(), loc_bf(1))
    zero["might"] = 0
    one = [put(g2, 0, a_unit(), loc_bf(1))]
    one[0]["might"] = 1
    # TWO defenders, and that is the whole point. With one defender, 465.2.c.4's
    # excess-damage tail puts the leftover point on it anyway, so calling zero
    # damage lethal produces the identical assignment by a different route and
    # the check cannot tell the two apart. With a second defender to spill onto,
    # it can.
    spare = put(g2, 1, a_unit(), loc_bf(1))
    spare["might"] = 1
    check("a 0-Might unit needs a non-zero assignment to take lethal damage (142.4.b)",
          combat.assign_damage(s2, one, [zero, spare]) == {zero["id"]: 1},
          "one point of Might, and it belongs on the 0-Might unit, not past it")
    # 465.2.c.2's reminder is that lethal is NON-ZERO damage, so a unit the pool
    # never reached is not lethally damaged however low its Might. Given a real
    # pool that goes somewhere else — the previous version passed an EMPTY pool,
    # where "nothing was assigned" is true of any implementation at all.
    shy = put(g2, 1, a_unit(), loc_bf(2 if len(s2.battlefields) > 2 else 0))
    shy["might"] = 0
    shy["backline"] = True
    ahead = put(g2, 1, shy["name"], shy["loc"])
    ahead["might"] = 1
    striker = put(g2, 0, a_unit(), shy["loc"])
    striker["might"] = 1
    unassigned = combat.assign_damage(s2, [striker], [shy, ahead]) == {ahead["id"]: 1}
    turn.run_cleanup(g2)
    check("and assigning nothing at all leaves it alive (465.2.c.2)",
          unassigned and shy["dmg"] == 0
          and shy["id"] in [u["id"] for u in s2.units],
          "Backline keeps the 0-Might unit last, the pool runs out on the other, "
          "and a unit with no damage marked survives the cleanup that kills the "
          "lethally damaged (323.5)")

    g3 = _combat_board(seed=51)
    log = texts(g3)
    check("combat sums the Might of both sides (465.2.a-b)",
          any("Might vs" in t for t in log))

    # 466.1.a.1, watched on a SURVIVOR. Asserting "nothing is damaged once the
    # combat is over" is true of an engine that never heals: everything that
    # took lethal damage is in the trash by then, and the Ending Phase heals
    # what is left. The heal is only observable on a unit that took damage and
    # lived, at the moment 466.3 is about to read the board.
    g3b = at_main(seed=53, auto_trivial=False)
    s3b = g3b.s
    s3b.battlefields[0]["ctrl"] = 0
    tough = put(g3b, 0, a_unit(), loc_bf(0))
    tough["might"] = 9
    nibbler = put(g3b, 1, a_unit(), loc_bf(0))
    nibbler["might"] = 1
    refresh(g3b)
    _open_combat(g3b, 0, 1)
    _run_damage(g3b, 0)
    hurt = tough["dmg"]
    turn.run_cleanup(g3b, "combat")
    healed = tough["dmg"]
    combat.result_step(g3b, 0)
    check("combat heals every unit before the result is determined (466.1.a.1)",
          hurt == 1 and healed == 0 and tough["id"] in [u["id"] for u in s3b.units],
          "a 9-Might defender took %d and is on %d when 466.3 reads the board"
          % (hurt, healed))
    check("a combat resolves to a named result (466.3)",
          any("combat result at" in t for t in log))
    check("combat ends and the turn leaves the Showdown State (466.7)",
          g3.s.showdown is None
          and any("ends" in t and "466.7" in t for t in log))

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
          s2.points[0] == s2.victory_target and s2.winner is None,
          "the point lands here; the WIN is 472's, and 472 happens at a cleanup")
    turn.run_cleanup(g2)
    check("and the cleanup that follows is where the game is won (472, 323.1)",
          s2.winner == 0)

    g3 = at_main(seed=83)
    g3.s.points[0] = g3.s.victory_target - 1
    g3.s.battlefields[0]["ctrl"] = 0
    g3.s.phase = "beginning"
    scoring.score(g3, 0, 0, method="Hold")
    turn.run_cleanup(g3)
    check("a Hold is not beholden to the final-point restriction (471.1.a.1)",
          g3.s.points[0] == g3.s.victory_target and g3.s.winner == 0)

    # 315.2.b.2 Holds ALL the battlefields the Turn Player controls. A player on
    # one point short therefore finishes the Scoring Step PAST the Victory
    # Score, because 472 is decided at the cleanup afterwards and not partway
    # through the step. Stopping at the target skips a Score the rules say
    # happens — and hides it, because the game is won either way.
    g3b = at_main(seed=85)
    held = g3b.s.turn_player
    for bf in g3b.s.battlefields:
        bf["ctrl"] = held
        put(g3b, held, a_unit(), loc_bf(bf["i"]))
    g3b.s.points[held] = g3b.s.victory_target - 1
    g3b.s.phase = "beginning"
    scoring.hold_all(g3b, held)
    check("a Turn Player one point short Holds EVERY battlefield, not just the "
          "one that wins (315.2.b.2)",
          g3b.s.points[held] == g3b.s.victory_target + 1
          and all(held in bf["scored"] for bf in g3b.s.battlefields),
          "%d points, scored %s" % (g3b.s.points[held],
                                    [bf["scored"] for bf in g3b.s.battlefields]))
    check("and the game is still won, at the cleanup (472, 323.1)",
          g3b.s.winner is None and turn.run_cleanup(g3b) is None
          and g3b.s.winner == held)

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

    # The old version of this ended in `or True`, so it read green whatever
    # happened — and it was the only check standing between a determinized world
    # and the real game. Written as a mutation of the WORLD, watched for on the
    # ORIGINAL: if any zone is shared, the original moves with it.
    before = (list(g.s.hand[0]), list(g.s.hand[1]), list(g.s.main_deck[1]),
              list(g.s.trash[0]), [dict(u) for u in g.s.units], list(g.s.points))
    w3 = g.apply_seed(seat, "gamma")
    w3.s.hand[1].append("A CARD THAT WAS NEVER DEALT")
    w3.s.main_deck[1].clear()
    w3.s.hand[0].clear()
    w3.s.trash[0].append("A CARD THAT WAS NEVER TRASHED")
    w3.s.points[0] += 99
    if w3.s.units:
        w3.s.units[0]["loc"] = "bf:1"
        w3.s.units[0]["dmg"] = 99
    after = (list(g.s.hand[0]), list(g.s.hand[1]), list(g.s.main_deck[1]),
             list(g.s.trash[0]), [dict(u) for u in g.s.units], list(g.s.points))
    check("a determinized world shares no zone with the game it came from",
          after == before,
          "search determinizes thousands of times against one position; a shared "
          "list makes the position drift under it")


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
    # perft, checked against a SECOND enumerator that shares no code with it.
    # "divide sums to perft" was the identity perft is defined by — it holds
    # however wrong both are. This walks the same tree with an explicit stack
    # instead of recursion, so the two agree only if the option generator agrees
    # with itself.
    board = perft.board("opening")
    check("perft agrees with an independent enumeration of the same tree",
          _leaves_by_stack(board.clone(), 3) == perft.perft(board.clone(), 3),
          "%d vs %d" % (_leaves_by_stack(board.clone(), 3),
                        perft.perft(board.clone(), 3)))
    parts = perft.divide(board.clone(), 3)
    root = board.clone().step()
    check("divide reports one row per legal option at the root, labelled",
          [key for _, key, _n in parts] == [o.key for o in root.options]
          and all(label and n >= 1 for label, _k, n in parts),
          "%d row(s) for %d option(s)" % (len(parts), len(root.options)))

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
    # Counted, not `all()`-ed. When every game crashes the Counter is empty and
    # `all()` over it is vacuously true — the check would have read green at the
    # exact moment nothing worked.
    named = sum(n for reason, n in ends.items()
                if reason and ("472" in reason or "431" in reason))
    check("and every game ends by a rule the log names",
          named == 24, "%d of 24 games ended by a named rule: %s"
                       % (named, "; ".join(sorted(ends)) or "none ended at all"))


def _leaves_by_stack(game, depth):
    """Leaves of the decision tree, by an explicit stack rather than recursion.

    A deliberate second implementation. It exists to disagree with `perft` if
    either is wrong, which the identity `sum(divide) == perft` cannot do.
    """
    stack = [(game, depth)]
    leaves = 0
    while stack:
        node, left = stack.pop()
        decision = node.step()
        if decision.terminal or left <= 0:
            leaves += 1
            continue
        for option in decision.options:
            child = node.clone()
            child.answer(option.key)
            stack.append((child, left - 1))
    return leaves


def engine_instruments_bite(check):
    """The instruments, audited: each one is shown a defect and must name it.

    Every other group asks "does the engine hold?". This asks "would the thing
    that watches the engine notice if it did not?" — which is the question that
    was never asked of the conservation invariants or of the golden comparison,
    both of which could have been gutted to `return []` with the whole suite
    still green.
    """
    # -- the conservation invariants ------------------------------------
    g = at_main(seed=31)
    check("a legal position reports no violations, so the rest of this means "
          "something", not invariants.check(g))

    broken = at_main(seed=31)
    broken.s.hand[0].append("A CARD FROM NOWHERE")
    check("the card-conservation invariant names a card that appeared from nowhere",
          any("not conserved" in v for v in invariants.check(broken)),
          "; ".join(invariants.check(broken))[:90])

    broken = at_main(seed=31)
    broken.s.rune_deck[1].append(broken.s.rune_deck[1][0])
    check("and it counts runes separately from Main Deck cards (416)",
          any("runes are not conserved" in v for v in invariants.check(broken)))

    broken = at_main(seed=31)
    broken.s.points[0] = -1
    check("the points invariant names a negative score",
          any("has -1 points" in v for v in invariants.check(broken)))

    broken = at_main(seed=31)
    broken.s.points[0] = broken.s.victory_target
    broken.s.tasks = [t for t in broken.s.tasks if t[0] != "cleanup"]
    check("the points invariant names a won game nothing is about to notice (472)",
          any("no Cleanup is outstanding" in v for v in invariants.check(broken)),
          "; ".join(invariants.check(broken))[:90])

    broken = at_main(seed=31)
    seat = broken.s.turn_player
    broken.s.chain.append({"id": "c90", "ctrl": seat, "name": "x", "kind": "spell",
                           "pending": True, "loc": "", "src": "hand"})
    broken.s.chain.append({"id": "c91", "ctrl": seat, "name": "y", "kind": "spell",
                           "pending": False, "loc": "", "src": "hand"})
    check("the Chain invariant names a finalized item sitting above a pending one",
          any("longer LIFO" in v for v in invariants.check(broken)))

    broken = at_main(seed=31)
    unit = put(broken, 0, a_unit(), loc_base(0))
    unit["loc"] = "nowhere:9"
    check("the location invariant names a permanent that is nowhere",
          any("not a location" in v for v in invariants.check(broken)))

    broken = at_main(seed=31)
    put(broken, 0, a_unit(), loc_base(0))
    broken.s.units[-1]["id"] = broken.s.units[0]["id"] if len(broken.s.units) > 1 \
        else broken.s.runes[0]["id"]
    check("the identity invariant names an id that answers for two objects",
          any("duplicate object id" in v for v in invariants.check(broken)))

    check("a broken position raises rather than being played on", raises(
        lambda: invariants.assert_ok(broken, "a test"), "invariant broken"))

    # -- the golden comparison ------------------------------------------
    recorded = goldens.load(goldens.PLAYTHROUGHS)
    fresh = json.loads(json.dumps(recorded))
    check("the golden comparison passes a record against itself",
          not goldens.compare(fresh, recorded))

    fresh = json.loads(json.dumps(recorded))
    fresh["games"][0]["answers"][3][2] = ["end"]
    check("the golden comparison names the decision whose ANSWER moved",
          any("decision 3 differs" in p for p in goldens.compare(fresh, recorded)))

    fresh = json.loads(json.dumps(recorded))
    fresh["games"][0]["step_hashes"][5] = "deadbeefdeadbeef"
    check("the golden comparison says a moved state hash means a rule changed",
          any("a rule changed" in p for p in goldens.compare(fresh, recorded)))

    fresh = json.loads(json.dumps(recorded))
    fresh["games"][0]["log"][2] = "a sentence nobody wrote"
    check("and tells a reworded log apart from a changed rule",
          any("wording, not rules" in p for p in goldens.compare(fresh, recorded)))

    fresh = json.loads(json.dumps(recorded))
    fresh["games"] = fresh["games"][1:]
    check("the golden comparison notices a game that stopped being played",
          any("no longer played" in p for p in goldens.compare(fresh, recorded)))

    # -- the generator ---------------------------------------------------
    deck = list(range(40))
    once, twice = list(deck), list(deck)
    state = rng.seed_from("shuffle-audit")
    rng.shuffle(state, once)
    rng.shuffle(state, twice)
    check("a shuffle is a permutation, and the same state shuffles the same way",
          sorted(once) == deck and once == twice and once != deck)
    other = list(deck)
    rng.shuffle(rng.seed_from("a different stream"), other)
    check("and a different stream gives a different permutation",
          other != once and sorted(other) == deck)


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

    # The half that was missing. A cover value used to be prose, and prose
    # cannot be wrong out loud: four entries named checks that did not exist,
    # and the coverage gate passed anyway because it only compared key sets.
    # Every claimed cover is now resolved against the names the suite actually
    # registered.
    registered = _registered_names()
    claimed = sorted(v for v in TRANSITION_COVER.values()
                     if not v.startswith("UNREACHABLE"))
    if registered is None:
        check("each covered transition names a check that ran", False,
              "the suite's name registry is not reachable from here")
    else:
        phantom = sorted(set(claimed) - registered)
        check("each covered transition names a check that ran, by its exact name",
              not phantom,
              "no such check: %s" % "; ".join(phantom) if phantom
              else "%d claim(s) resolved" % len(set(claimed)))
    check("the vendored transitions record the corpus they were verified against",
          all(p.get("corpus", {}).get("CR") for p in vendored["primers"].values()),
          ", ".join("%s: CR %s" % (k, v["corpus"]["CR"])
                    for k, v in sorted(vendored["primers"].items())))
    check("the vendored transitions still match the primers they came from",
          _primers_agree(vendored), _primers_agree_detail(vendored))


def _registered_names():
    """Every check name the running suite has registered, or None.

    The parent suite is `__main__` when `selftest.py` is run directly and
    `selftest` when `deck_cli` imports it. Both are looked up rather than
    imported: importing it under the other name would build a SECOND, empty
    registry and this gate would then pass by comparing against nothing.
    """
    for key in ("__main__", "selftest"):
        module = sys.modules.get(key)
        if module is not None and hasattr(module, "NAMES"):
            return set(module.NAMES)
    return None


def _failed_names():
    """Every check the running suite has recorded as failed, or None."""
    for key in ("__main__", "selftest"):
        module = sys.modules.get(key)
        if module is not None and hasattr(module, "FAILS"):
            return set(module.FAILS)
    return None


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


# -- combat fixtures -----------------------------------------------------

def _open_combat(g, index=0, attacker=1):
    """Open a Combat Showdown at a battlefield the caller has already filled.

    Straight to 464.2 without the Showdown window, because what most of these
    checks are about is what happens after it closes. `closed` is what
    `chain.close_showdown` sets, and the Steps of Combat read it.
    """
    bf = g.s.battlefields[index]
    bf["contested"] = True
    bf["contested_by"] = attacker
    turn.open_showdown(g, index, combat=True)
    g.s.showdown["closed"] = True
    return bf


def _run_damage(g, index=0, pick=0):
    """The Damage Step, answering every assignment with the `pick`th option."""
    combat.damage_step(g, index)
    for _ in range(64):
        if not (g.s.choosing and g.s.choosing.get("what") == "assign_damage"):
            return
        decision = g.step()
        if decision.terminal:
            return
        g.answer(decision.options[min(pick, len(decision.options) - 1)])
    raise AssertionError("the damage assignment never finished")


def _resolution(g, index=0):
    """466.1 through 466.7, as the Tasks `chain.close_showdown` queues them."""
    turn.run_cleanup(g, "combat")
    combat.result_step(g, index)
    combat.control_step(g, index)
    combat.end_step(g, index)


def _fight(g, index=0, pick=0):
    _run_damage(g, index, pick)
    _resolution(g, index)


def _two_on_two(seed=101, attacker=1, might=(5, 5, 2, 2)):
    """One attacker and two defenders at bf:0, with the Might the caller names."""
    g = at_main(seed=seed, auto_trivial=False)
    s = g.s
    s.battlefields[0]["ctrl"] = 1 - attacker
    a1 = put(g, attacker, a_unit(), loc_bf(0))
    a1["might"] = might[0]
    d1 = put(g, 1 - attacker, a_unit(), loc_bf(0))
    d1["might"] = might[2]
    d2 = put(g, 1 - attacker, a_unit(), loc_bf(0))
    d2["might"] = might[3]
    refresh(g)
    _open_combat(g, 0, attacker)
    return g, a1, d1, d2


#: Boards for the brute-force equivalence sweep. Small on purpose — every
#: assignment of the pool over the defenders is enumerated — and chosen so the
#: keyword orderings, an over-lethal excess and a pool that runs out short are
#: all inside the set. "T" is Tank, "B" is Backline, "TB" is the unit 465.2.c.8
#: would hand its controller a choice about.
_ASSIGNMENT_SHAPES = (
    {"name": "7 onto 3 and 2", "seed": 311, "might": 7,
     "defenders": ((3, ""), (2, ""))},
    {"name": "4 onto 2 and 2", "seed": 313, "might": 4,
     "defenders": ((2, ""), (2, ""))},
    {"name": "3 onto 2 and 2 — the pool runs out", "seed": 317, "might": 3,
     "defenders": ((2, ""), (2, ""))},
    {"name": "5 onto a Tank, a plain and a Backline", "seed": 331, "might": 5,
     "defenders": ((2, "T"), (1, ""), (1, "B"))},
    {"name": "4 onto Tank-and-Backline and a plain", "seed": 337, "might": 4,
     "defenders": ((2, "TB"), (2, ""))},
    {"name": "2 onto a 0-Might unit and a 1-Might unit", "seed": 347, "might": 2,
     "defenders": ((0, ""), (1, ""))},
)


def _every_assignment(defenders, pool):
    """Every {id: amount} map over `defenders` totalling at most `pool`."""
    out = []

    def walk(index, so_far, left):
        if index == len(defenders):
            out.append(dict((k, v) for k, v in so_far.items() if v))
            return
        for amount in range(left + 1):
            so_far[defenders[index]["id"]] = amount
            walk(index + 1, so_far, left - amount)
        so_far.pop(defenders[index]["id"], None)

    walk(0, {}, pool)
    return out


def engine_designations(check):
    """464.2.c, 323.2 and 466.7.a — the designations combat is read through."""
    g, a1, d1, d2 = _two_on_two(seed=103)
    check("every unit at the battlefield takes its controller's designation "
          "(464.2.c.3)",
          a1["role"] == "attacker" and d1["role"] == "defender"
          and d2["role"] == "defender",
          "%s / %s / %s" % (a1["role"], d1["role"], d2["role"]))
    check("the Attacking and Defending units are read by designation, not by side "
          "(465.2.a-b)",
          [u["id"] for u in combat.attacking_units(g.s, 0)] == [a1["id"]]
          and [u["id"] for u in combat.defending_units(g.s, 0)]
          == [d1["id"], d2["id"]])

    # 464.2.c.3.a: a unit that becomes present later is designated in the
    # Cleanup that follows, which is 323.2.a.
    # 464.2.c.3.a defers the designation to the next Cleanup. The "it has none
    # yet" half is not checked here: it is `new_unit`'s own default, and a check
    # that a constructor returns what it was written to return is a check of the
    # test fixture. What IS observable is the designation arriving.
    late = put(g, 1, a_unit(), loc_bf(0))
    turn.run_cleanup(g)
    check("and the next cleanup gives it its controller's designation (323.2.a)",
          late["role"] == "attacker")

    # 323.2.b: a unit holding the wrong designation swaps.
    late["role"] = "defender"
    turn.run_cleanup(g)
    check("a unit designated the opposite of its controller is corrected (323.2.b)",
          late["role"] == "attacker")

    # 323.2.c: a unit anywhere else loses it.
    late["loc"] = loc_base(1)
    turn.run_cleanup(g)
    check("a unit that leaves the battlefield loses its designation (323.2.c)",
          late["role"] is None)

    g2, a2, d3, _d4 = _two_on_two(seed=107)
    _fight(g2)
    check("combat ends by removing the designation from every unit and player "
          "(466.7.a)",
          all(u["role"] is None for u in g2.s.units) and g2.s.combat_attacker is None,
          "attacker was seat %r" % g2.s.combat_attacker)

    # 464.2.c.1.b: a Showdown already ongoing when the Combat opens keeps the
    # player who has Focus. Only the designations are established.
    g3 = at_main(seed=109, auto_trivial=False)
    s3 = g3.s
    s3.battlefields[0]["ctrl"] = 0
    put(g3, 1, a_unit(), loc_bf(0))
    s3.battlefields[0]["contested"] = True
    s3.battlefields[0]["contested_by"] = 1
    refresh(g3)
    turn.open_showdown(g3, 0, combat=False)
    s3.showdown["focus"] = 0                     # a pass has moved it (347.2.b)
    combat.strip_designations(g3)
    holder = put(g3, 0, a_unit(), loc_bf(0))
    s3.battlefields[0]["cb_staged"] = True
    turn.cleanup_once(g3)
    check("a Showdown that becomes a Combat Showdown keeps whoever has Focus "
          "(464.2.c.1.b)",
          s3.showdown["focus"] == 0 and s3.showdown["combat"],
          "focus %r" % (s3.showdown or {}).get("focus"))
    check("and it still establishes the designations (323.14, 464.2.c.3)",
          s3.combat_attacker == 1 and holder["role"] == "defender")

    # The invariant, audited: shown a designation that 323.2 would not have
    # made, it must name it. Everything about combat is read through these, so
    # an undesignated unit does not crash — it silently stops fighting.
    g4, a4, d4, _e4 = _two_on_two(seed=111)
    d4["role"] = None
    check("the designation invariant names a unit 323.2 should have designated",
          any("323.2 says it should be" in v for v in invariants.check(g4)),
          "; ".join(invariants.check(g4))[:90])
    g5, a5, _d5, _e5 = _two_on_two(seed=111)
    _fight(g5)
    a5["role"] = "attacker"
    check("and a designation left behind once combat is over (466.7.a)",
          any("no Combat in progress" in v for v in invariants.check(g5)),
          "; ".join(invariants.check(g5))[:90])


def engine_assignment(check):
    """465.2.c as a decision, and the validation that any answer obeys it."""
    g, a1, d1, d2 = _two_on_two(seed=113)
    combat.damage_step(g, 0)
    decision = g.step()
    check("the damage assignment is a decision when more than one unit can take "
          "it (465.2.c)",
          decision.kind == "assign_damage"
          and sorted(o.key[1] for o in decision.options) == sorted(
              [d1["id"], d2["id"]]),
          "%s with %d option(s)" % (decision.kind, len(decision.options)))
    check("and it is asked of the Attacker first (465.2.c)", decision.seat == 1)
    check("the first option is the engine's own lethal-first assignment "
          "(465.2.c.3)",
          decision.options[0].key[1:] == (d1["id"],
                                          combat.assign_damage(g.s, [a1],
                                                               [d1, d2])[d1["id"]]),
          decision.options[0].label)

    g2, a2, e1, e2 = _two_on_two(seed=113)
    # Taken BEFORE the damage lands: once the defenders are dead-marked, the
    # engine's own assignment for the same board is the empty one, and the
    # comparison would be {} == {} whatever either side did.
    want = combat.assign_damage(g2.s, [a2], [e1, e2])
    _run_damage(g2, 0, pick=0)
    by_first_option = dict((u["id"], u["dmg"]) for u in (e1, e2) if u["dmg"])
    check("taking the first option at every step reproduces `assign_damage` "
          "exactly (465.2.c.7)",
          by_first_option == want, "%r vs %r" % (by_first_option, want))

    g3, a3, f1, f2 = _two_on_two(seed=113)
    # Taken before the damage lands, for the same reason as `want` above: once
    # both defenders are dead-marked, every question about what may be assigned
    # to them answers "nothing".
    legal = combat.legal_assignments(g3.s, [a3], [f1, f2])
    _run_damage(g3, 0, pick=1)
    landed = tuple(sorted((u["id"], u["dmg"]) for u in (f1, f2) if u["dmg"]))
    check("and a different answer is a different, still legal, assignment "
          "(465.2.c.7)",
          landed in legal and landed != tuple(sorted(
              combat.assign_damage(g3.s, [a3], [f1, f2]).items())),
          "%r, out of %d legal assignment(s)" % (landed, len(legal)))

    # 465.2.c.4: the excess is allowed only once nothing else can take damage.
    g4 = at_main(seed=117)
    big = put(g4, 0, a_unit(), loc_bf(0))
    big["might"] = 4
    lone = put(g4, 1, a_unit(), loc_bf(0))
    lone["might"] = 2
    check("no more than the minimum lethal lands while it is the only target "
          "(465.2.c.4)",
          combat.assign_damage(g4.s, [big], [lone]) == {lone["id"]: 4},
          "the excess has nowhere else to go, so it stays on the last unit")

    # The validator. Each clause is shown an assignment that breaks exactly it.
    s4 = g4.s
    spare = put(g4, 1, a_unit(), loc_bf(0))
    spare["might"] = 2
    check("an assignment naming a unit that is not in this combat is refused "
          "(465.2.c)",
          any("not a unit on the other side" in v for v in
              combat.validate_assignment(s4, [big], [lone], {spare["id"]: 2})))
    check("an assignment of zero damage is refused (465.2.c)",
          any("a positive amount" in v for v in
              combat.validate_assignment(s4, [big], [lone, spare],
                                         {lone["id"]: 0})))
    check("assigning more than the summed Might is refused (465.2.a-c)",
          any("summed Might" in v for v in
              combat.validate_assignment(s4, [big], [lone, spare],
                                         {lone["id"]: 2, spare["id"]: 9})))
    check("leaving damage unassigned while a unit could take it is refused "
          "(465.2.c.6)",
          any("had somewhere to go" in v for v in
              combat.validate_assignment(s4, [big], [lone, spare],
                                         {lone["id"]: 2})))
    # The clause that was missing: with everything already lethal the pool STILL
    # has to be spent, because 465.2.c.4 puts the excess on the last unit
    # assigned. `pending_targets` is empty at that point, so a check written
    # against it accepted 5 of 7 damage assigned and called it legal.
    # A pool bigger than the lethal total: 465.2.c.4 puts the excess on the last
    # unit assigned, so leaving it unspent is illegal even though every unit is
    # already dead-marked. `pending_targets` is empty there, and a check written
    # against it accepted 4 of 7 damage assigned and called it legal.
    huge = put(g4, 0, a_unit(), loc_bf(0))
    huge["might"] = 7
    check("and so is stopping early once every unit happens to be lethal "
          "(465.2.c)",
          any("had somewhere to go" in v for v in
              combat.validate_assignment(s4, [huge], [lone, spare],
                                         {lone["id"]: 2, spare["id"]: 2})),
          "%r" % combat.validate_assignment(s4, [huge], [lone, spare],
                                            {lone["id"]: 2, spare["id"]: 2}))
    # Two units left short needs a pool small enough that BOTH could be: with
    # a 4-Might attacker one of them is over its lethal instead, which is a
    # different clause and would let this check pass for the wrong reason.
    small = put(g4, 0, a_unit(), loc_bf(0))
    small["might"] = 2
    check("two units left short of lethal is refused (465.2.c.3)",
          any("465.2.c.3" in v for v in
              combat.validate_assignment(s4, [small], [lone, spare],
                                         {lone["id"]: 1, spare["id"]: 1})))
    check("piling the excess on one unit while another is untouched is refused "
          "(465.2.c.4)",
          any("465.2.c.4" in v for v in
              combat.validate_assignment(s4, [big], [lone, spare],
                                         {lone["id"]: 4})))
    check("the engine's own assignment passes its own validator (465.2.c.6)",
          not combat.validate_assignment(
              s4, [big], [lone, spare],
              combat.assign_damage(s4, [big], [lone, spare])))

    # The validator and the option list must accept exactly the same set. They
    # did not: 7 Might onto a 3-Might and a 2-Might unit has two legal
    # assignments and the hand-written clauses accepted six. This brute-forces
    # every assignment of the pool over the defenders and requires the two
    # answers to agree, on boards that include the keyword orderings.
    disagreed = []
    boards = 0
    for shape in _ASSIGNMENT_SHAPES:
        gb = at_main(seed=shape["seed"])
        sb = gb.s
        hitter = put(gb, 0, a_unit(), loc_bf(0))
        hitter["might"] = shape["might"]
        defs = []
        for spec in shape["defenders"]:
            unit = put(gb, 1, a_unit(), loc_bf(0))
            unit["might"] = spec[0]
            unit["tank"] = "T" in spec[1]
            unit["backline"] = "B" in spec[1]
            defs.append(unit)
        boards += 1
        generated = combat.legal_assignments(sb, [hitter], defs)
        for candidate in _every_assignment(defs, shape["might"]):
            accepted = not combat.validate_assignment(sb, [hitter], defs, candidate)
            expected = tuple(sorted(candidate.items())) in generated
            if accepted != expected:
                disagreed.append("%s: %r %s" % (shape["name"], candidate,
                                                "accepted" if accepted else "refused"))
    check("the validator accepts exactly the assignments the option list "
          "generates (465.2.c)",
          not disagreed,
          "; ".join(disagreed[:2]) if disagreed
          else "%d board(s), every assignment of the pool brute-forced" % boards)

    g5, a5, g1, g2u = _two_on_two(seed=119)
    g5.s.choosing = {"what": "assign_damage", "bf": 0, "attacker": 1, "by": 1,
                     "pool": 5, "onto": [(g1["id"], 1), (g2u["id"], 1)],
                     "first": None}
    check("an assignment built outside the option list is still refused "
          "(465.2.c.6)",
          raises(lambda: combat.assignment_done(g5), "not legal"))


def engine_keywords(check):
    """The combat keywords, as unit flags with the rules that consume them."""
    g = at_main(seed=127)
    s = g.s
    unit = put(g, 0, a_unit(), loc_bf(0))
    unit["might"] = 3

    # 807.1.c / 814.1.c: conditional on the DESIGNATION, not on the side.
    unit["assault"] = 2
    unit["shield"] = 1
    unit["role"] = "attacker"
    attacking = s.might_of(unit)
    unit["role"] = "defender"
    defending = s.might_of(unit)
    unit["role"] = None
    check("Assault adds Might only while the unit is an attacker (807.1.c, 807.1.d)",
          attacking == 5 and s.might_of(unit) == 3, "%d attacking" % attacking)
    check("Shield adds Might only while the unit is a defender (814.1.c, 814.1.d)",
          defending == 4 and s.might_of(unit) == 3, "%d defending" % defending)

    # 703 / 708 / 710: Mighty is a reading of CURRENT Might. FOUR Might, not
    # three: 708's threshold is 5, and a 3-Might unit is below every plausible
    # wrong threshold as well as the right one.
    unit["might"] = 4
    check("a unit below 5 Might is not Mighty (708)", not s.is_mighty(unit),
          "%d Might" % s.might_of(unit))
    unit["buffs"] = 1
    check("a buff that takes a unit to 5 Might makes it Mighty (703, 709, 710)",
          s.is_mighty(unit), "%d Might" % s.might_of(unit))
    unit["buffs"] = 0
    unit["shield"] = 0
    unit["role"] = None

    # 712-715: Bonus Damage, summed once, never negative.
    one = put(g, 0, a_unit(), loc_bf(1))
    one["might"] = 1
    two = put(g, 0, a_unit(), loc_bf(1))
    two["might"] = 1
    one["bonus"] = 2
    two["bonus"] = 3
    check("Bonus Damage from several sources is summed and applied once (714)",
          combat.damage_pool(s, [one, two]) == 1 + 1 + 5,
          "%d" % combat.damage_pool(s, [one, two]))
    one["bonus"] = -9
    two["bonus"] = 0
    check("a negative Bonus Damage is no bonus at all, not a reduction (714.2)",
          combat.bonus_damage([one, two]) == 0
          and combat.damage_pool(s, [one, two]) == 2)
    one["bonus"] = 1
    victim = put(g, 1, a_unit(), loc_bf(1))
    victim["might"] = 3
    check("Bonus Damage lands on the assignment, not after it (465.2.c.5, 715)",
          combat.assign_damage(s, [one, two], [victim]) == {victim["id"]: 3},
          "2 Might plus 1 Bonus Damage is exactly lethal on a 3-Might unit")
    one["bonus"] = 0

    # 809: Deflect is a cost an OPPONENT pays, and only an opponent.
    guarded = put(g, 0, a_unit(), loc_base(0))
    guarded["deflect"] = 2
    check("Deflect makes an opponent's spell cost that much more Power (809.1.c)",
          actions.deflect_surcharge(guarded, 1) == 2)
    check("and costs its own controller nothing (809.1.c)",
          actions.deflect_surcharge(guarded, 0) == 0)

    # 815 / 826: the assignment-order keywords.
    g2 = at_main(seed=131)
    s2 = g2.s
    hitter = put(g2, 0, a_unit(), loc_bf(0))
    hitter["might"] = 6
    tank = put(g2, 1, a_unit(), loc_bf(0))
    tank["might"] = 2
    tank["tank"] = True
    plain = put(g2, 1, a_unit(), loc_bf(0))
    plain["might"] = 2
    back = put(g2, 1, a_unit(), loc_bf(0))
    back["might"] = 2
    back["backline"] = True
    order = [tank, plain, back]
    check("a Tank is the only legal assignment until it has its lethal (815.1.c.2)",
          [u["id"] for u in combat.eligible_targets(s2, order, {})] == [tank["id"]])
    check("once the Tank has its lethal the plain units become legal (815.1.c.2)",
          [u["id"] for u in combat.eligible_targets(s2, order, {tank["id"]: 2})]
          == [plain["id"]])
    # Backline, with no Tank in the picture. Asking it of a board where the Tank
    # has just been finished proves nothing about Backline: `pending` is down to
    # one unit by then, so deleting the Backline rule altogether still answers
    # [back]. Two units, one of them Backline, is the smallest board where the
    # rule is the only thing that decides the answer.
    check("a Backline unit is not a legal assignment while another unit can "
          "take damage (826.4.b)",
          [u["id"] for u in combat.eligible_targets(s2, [plain, back], {})]
          == [plain["id"]],
          "%r" % [u["id"] for u in combat.eligible_targets(s2, [plain, back], {})])
    check("and it becomes one once nothing else can (826.4.b)",
          [u["id"] for u in combat.eligible_targets(
              s2, [plain, back], {plain["id"]: 2})] == [back["id"]])
    check("so the whole assignment runs Tank, then plain, then Backline (465.2.c.6)",
          combat.assign_damage(s2, [hitter], order)
          == {tank["id"]: 2, plain["id"]: 2, back["id"]: 2})
    check("jumping a Tank is refused (815.1.c.2)",
          any("815.1.c.2" in v for v in combat.validate_assignment(
              s2, [hitter], order, {plain["id"]: 2, back["id"]: 2,
                                    tank["id"]: 2})) is False
          and any("815.1.c.2" in v for v in combat.validate_assignment(
              s2, [hitter], order, {plain["id"]: 6})))
    check("assigning to Backline before the rest is refused (826.4.b)",
          any("826.4.b" in v for v in combat.validate_assignment(
              s2, [hitter], order, {tank["id"]: 2, back["id"]: 4})))

    # A unit with both keywords: 465.2.c.8 gives the player the choice and this
    # slice does not model it. Tank wins, and the gap is written down.
    both = put(g2, 1, a_unit(), loc_bf(1))
    both["tank"] = True
    both["backline"] = True
    both["might"] = 1
    other = put(g2, 1, a_unit(), loc_bf(1))
    other["might"] = 1
    check("a unit with both Tank and Backline is assigned as a Tank (465.2.c.8)",
          [u["id"] for u in combat.eligible_targets(s2, [both, other], {})]
          == [both["id"]],
          "465.2.c.8's choice of which requirement applies is a declared gap")


def engine_combat_steps(check):
    """The three steps, their windows, and what each one does (464-466)."""
    # 465.1: with one side gone the Damage Step's Tasks never become outstanding.
    g = at_main(seed=137, auto_trivial=False)
    s = g.s
    s.battlefields[0]["ctrl"] = 0
    put(g, 0, a_unit(), loc_bf(0))
    put(g, 1, a_unit(), loc_bf(0))
    refresh(g)
    _open_combat(g, 0, 1)
    for unit in list(s.units):
        if unit["ctrl"] == 1:
            actions.to_trash(g, unit["id"], reason="a test removes it")
    mark = len(g.log)
    combat.damage_step(g, 0)
    check("a combat with one side gone skips the Damage Step (465.1)",
          any("465.1" in e["text"] for e in g.log[mark:]) and s.choosing is None,
          "no assignment is asked and no damage is dealt")

    # 465.3: the Damage Step cancels what the Showdown left outstanding.
    g2, _a, _d1, _d2 = _two_on_two(seed=139)
    g2.s.tasks = [("cleanup", "combat"), ("combat_result", 0), ("draw", None),
                  ("cleanup", "")]
    _run_damage(g2, 0)
    check("the Damage Step cancels the Tasks the Showdown left outstanding "
          "(465.3)",
          ("draw", None) not in g2.s.tasks and ("cleanup", "") not in g2.s.tasks
          and ("cleanup", "combat") in g2.s.tasks,
          "%r" % (g2.s.tasks,))

    # 466.2 / 466.4 / 466.6: the window between the Resolution Step's steps.
    g3 = at_main(seed=141, auto_trivial=False)
    s3 = g3.s
    name = s3.hand[0][0]
    s3.hand[0].remove(name)
    s3.chain.append({"id": s3.mint("c"), "ctrl": 0, "name": name, "kind": "spell",
                     "pending": False, "loc": "", "src": "hand"})
    s3.passes = 2
    turn.run_task(g3, "combat_fepr", 0)
    check("the Resolution Step's window re-queues itself while the Chain has "
          "something on it (466.2)",
          ("combat_fepr", 0) in s3.tasks)
    for _ in range(8):
        if not s3.chain:
            break
        s3.tasks.remove(("combat_fepr", 0))
        s3.passes = 2
        turn.run_task(g3, "combat_fepr", 0)
    check("and it resolves that item before the next step of Combat runs "
          "(466.2, 340.1)",
          not s3.chain and name in s3.trash[0])
    s3.tasks = [t for t in s3.tasks if t[0] != "combat_fepr"]
    turn.run_task(g3, "combat_fepr", 0)
    check("with an empty Chain the window passes straight through (466.4, 466.6)",
          ("combat_fepr", 0) not in s3.tasks)

    # 460: a Combat opens in a Cleanup, at a battlefield the Turn Player picks.
    g4 = at_main(seed=143)
    s4 = g4.s
    s4.battlefields[0]["ctrl"] = 0
    put(g4, 0, a_unit(), loc_bf(0))
    intruder = put(g4, 1, a_unit(), loc_bf(0))
    s4.battlefields[0]["contested"] = True
    s4.battlefields[0]["contested_by"] = 1
    refresh(g4)
    turn.run_cleanup(g4)
    check("a Combat opens at a cleanup, at a battlefield the Turn Player chooses "
          "(323.13)",
          s4.showdown is not None and s4.showdown["combat"]
          and s4.showdown["bf"] == 0
          and any("COMBAT opens" in e["text"] for e in g4.log))

    # 461.2: a staged Combat that stops being staged is never resolved. Staged
    # in a CLOSED state, because 323.13 opens it the moment the state is open
    # and there would be nothing left to stop being staged.
    g5 = at_main(seed=145)
    s5 = g5.s
    s5.battlefields[0]["ctrl"] = 0
    put(g5, 0, a_unit(), loc_bf(0))
    intruder = put(g5, 1, a_unit(), loc_bf(0))
    s5.battlefields[0]["contested"] = True
    s5.battlefields[0]["contested_by"] = 1
    held = s5.hand[0].pop()
    s5.chain.append({"id": s5.mint("c"), "ctrl": 0, "name": held, "kind": "spell",
                     "pending": True, "loc": "", "src": "hand"})
    refresh(g5)
    turn.cleanup_once(g5)
    staged = s5.battlefields[0]["cb_staged"]
    intruder["loc"] = loc_base(1)
    turn.cleanup_once(g5)
    check("a Combat that stops being staged before it opens is not resolved "
          "(461.2, 323.10)",
          staged and not s5.battlefields[0]["cb_staged"] and s5.showdown is None,
          "staged=%r" % staged)

    # 465.2.c.1.a: assigned by both, then dealt at once.
    g5 = at_main(seed=147, auto_trivial=False)
    s5 = g5.s
    s5.battlefields[0]["ctrl"] = 0
    mine = put(g5, 0, a_unit(), loc_bf(0))
    mine["might"] = 3
    theirs = put(g5, 1, a_unit(), loc_bf(0))
    theirs["might"] = 3
    refresh(g5)
    _open_combat(g5, 0, 1)
    _fight(g5)
    check("equal Might trades both units simultaneously (465.2.c.1.a)",
          not s5.units_at(loc_bf(0))
          and s5.trash[0].count(mine["name"]) + s5.trash[1].count(theirs["name"]) >= 2,
          "neither survived to establish control")

    # 466.5.d: taking the battlefield is a Conquer, and it happens INSIDE the
    # Resolution Step — for the attacker who won it as much as for the defender
    # who held. The engine used to stand down here whenever the winner was the
    # attacker, because 466.1's Cleanup had re-marked a Showdown staged (323.8)
    # at a battlefield that is still Contested by a player with units on it. The
    # point arrived a cleanup later through a Showdown the rules never open.
    g6 = at_main(seed=149, auto_trivial=False)
    s6 = g6.s
    winner = put(g6, 1, a_unit(), loc_bf(0))
    winner["might"] = 6
    loser = put(g6, 0, a_unit(), loc_bf(0))
    loser["might"] = 1
    s6.battlefields[0]["ctrl"] = 0
    before = s6.points[1]
    refresh(g6)
    _open_combat(g6, 0, 1)
    _fight(g6)
    check("winning a combat establishes control and Conquers (466.5.d)",
          s6.battlefields[0]["ctrl"] == 1 and s6.points[1] == before + 1
          and not s6.battlefields[0]["contested"],
          "seat 1 holds %r on %d point(s)"
          % (s6.battlefields[0]["ctrl"], s6.points[1]))
    # 466.5.a cleared Contested, so the Cleanup 466.7 queues finds nothing to
    # stage (323.8) and no second Showdown opens over a battlefield that is
    # already settled. That is the whole point of doing 466.5 in the step.
    turn.run_cleanup(g6)
    check("and the battlefield is left with nothing staged, so no second "
          "Showdown opens over it (466.5.a, 323.8)",
          not s6.battlefields[0]["sd_staged"]
          and not s6.battlefields[0]["cb_staged"]
          and s6.showdown is None,
          "staged %r/%r, showdown %r" % (s6.battlefields[0]["sd_staged"],
                                         s6.battlefields[0]["cb_staged"],
                                         s6.showdown))

    # 703 + 142.4.b: Might decides who dies, and it is read at the Damage Step.
    g7 = at_main(seed=151, auto_trivial=False)
    s7 = g7.s
    hitter = put(g7, 1, a_unit(), loc_bf(0))
    hitter["might"] = 3
    tough = put(g7, 0, a_unit(), loc_bf(0))
    tough["might"] = 2
    tough["buffs"] = 2
    s7.battlefields[0]["ctrl"] = 0
    refresh(g7)
    _open_combat(g7, 0, 1)
    _run_damage(g7)
    check("a Might change applied before combat changes who dies (703, 142.4.b)",
          tough["dmg"] == 3 and tough["dmg"] < s7.might_of(tough),
          "at 4 Might it survives the 3 damage that would kill it at 2")

    # 323.5: outside combat too.
    g8 = at_main(seed=153)
    hurt = put(g8, 0, a_unit(), loc_base(0))
    hurt["dmg"] = hurt["might"] or 1
    hurt["might"] = hurt["dmg"]
    turn.run_cleanup(g8)
    check("a unit with lethal damage marked is killed at a cleanup (323.5)",
          hurt["id"] not in [u["id"] for u in g8.s.units])

    # 190.3.a: Contested is applied by a UNIT.
    g9 = at_main(seed=157)
    gear = next((n for n in sorted(set(two_decks()[0].main_cards()))
                 if turn.category(n) == "gear"), None)
    if gear is None:
        check("gear arriving at a battlefield does not contest it (190.3.a)", False,
              "the fixture deck has no Gear to place")
    else:
        actions.put_into_play(g9, 0, gear, loc_bf(0), False, "main_deck")
        check("gear arriving at a battlefield does not contest it (190.3.a)",
              not g9.s.battlefields[0]["contested"])


def engine_resources(check):
    """Runes, the pool, and paying a printed cost (163-168, 356-357, 429-430)."""
    g = at_main(seed=163)
    s = g.s
    seat = 0
    s.energy[seat] = 0
    s.power[seat] = {}
    mine = [r for r in s.runes if r["ctrl"] == seat]
    for rune in mine:
        rune["exh"] = False
    if len(mine) < 2:
        actions.channel(g, seat, 2 - len(mine))
        mine = [r for r in s.runes if r["ctrl"] == seat]

    actions.tap_for_energy(g, seat, 1)
    check("exhausting a rune adds 1 Energy (164.2.a)",
          s.energy[seat] == 1 and sum(1 for r in mine if r["exh"]) == 1)
    check("exhausting an already-exhausted object is refused (414)",
          raises(lambda: actions.exhaust(g, next(r["id"] for r in mine if r["exh"])),
                 "already exhausted"))

    ready_rune = next(r for r in s.runes if r["ctrl"] == seat and not r["exh"])
    deck_before = len(s.rune_deck[seat])
    actions.recycle_rune_for_power(g, seat, ready_rune["id"])
    check("recycling a rune adds Power of its domain (164.2.b.1)",
          sum(s.power[seat].values()) == 1
          and (ready_rune["domain"] or "Universal") in s.power[seat])
    check("a recycled rune returns to the Rune Deck, not the Main Deck (161.2.b)",
          len(s.rune_deck[seat]) == deck_before + 1
          and ready_rune["name"] == s.rune_deck[seat][-1]
          and ready_rune["id"] not in [r["id"] for r in s.runes])
    check("a rune id that is not a rune is refused",
          raises(lambda: actions.recycle_rune_for_power(g, seat, "r999"),
                 "not controlled by"))
    other_rune = next((r for r in s.runes if r["ctrl"] == 1), None)
    if other_rune is None:
        actions.channel(g, 1, 1)
        other_rune = next(r for r in s.runes if r["ctrl"] == 1)
    check("a rune cannot be recycled by a player who does not control it",
          raises(lambda: actions.recycle_rune_for_power(g, 0, other_rune["id"]),
                 "not controlled by"))

    # Paying (356-357). A cheap card the fixture deck really holds.
    g2 = at_main(seed=167)
    s2 = g2.s
    name = min(sorted(set(two_decks()[0].main_cards())),
               key=lambda n: (cards.energy_cost(n) or 0, n))
    cost = actions.cost_of(name)
    s2.energy[0] = 0
    s2.power[0] = {}
    for rune in [r for r in s2.runes if r["ctrl"] == 0]:
        s2.runes.remove(rune)
    for _ in range(cost["energy"] + cost["power"] + 1):
        actions.channel(g2, 0, 1)
    check("a cost is payable from readied runes (357)",
          actions.can_pay(g2, 0, name)[0], name)
    actions.pay(g2, 0, name)
    check("paying leaves the pool at zero (357)",
          s2.energy[0] == 0 and not s2.power[0])

    g3 = at_main(seed=167)
    s3 = g3.s
    dear = max(sorted(set(two_decks()[0].main_cards())),
               key=lambda n: (cards.energy_cost(n) or 0, n))
    s3.energy[0] = 0
    s3.power[0] = {}
    for rune in [r for r in s3.runes if r["ctrl"] == 0]:
        s3.runes.remove(rune)
    ok, why = actions.can_pay(g3, 0, dear)
    check("a cost beyond the runes available is refused, with the reason (358)",
          not ok and ("needs" in why), why)
    check("an unpayable cost raises rather than going through (357)",
          raises(lambda: actions.pay(g3, 0, dear), "cannot pay"))
    check("`pay` still refuses when `can_pay` wrongly says yes",
          raises(lambda: actions.tap_for_energy(g3, 0, 99), "readied rune"))

    # 164.2.b: the Power ability's cost is "Recycle this", not "[E]", so an
    # EXHAUSTED rune can still pay it. Requiring a readied one refuses payments
    # the rules allow, and does it silently — the card just stops being playable.
    g4 = at_main(seed=173)
    s4 = g4.s
    for rune in [r for r in s4.runes if r["ctrl"] == 0]:
        s4.runes.remove(rune)
    s4.energy[0] = 0
    s4.power[0] = {}
    powered, rune_name = _power_card_and_rune(two_decks()[0])
    check("the fixture deck holds a card with a Power symbol to pay",
          powered is not None, powered or "none found")
    cost = actions.cost_of(powered)
    spent = new_rune(s4.mint("r"), rune_name, 0, True)
    s4.runes.append(spent)
    actions.channel(g4, 0, cost["energy"])
    check("Power can be recycled from an EXHAUSTED rune (164.2.b)",
          actions.can_pay(g4, 0, powered)[0], powered)
    actions.pay(g4, 0, powered)
    check("and paying that way actually recycles the rune (416)",
          spent["id"] not in [r["id"] for r in s4.runes]
          and spent["name"] in s4.rune_deck[0])


def _power_card_and_rune(deck):
    """A card with exactly one Power symbol, and a rune of a domain that pays it."""
    runes = sorted(set(deck.rune_cards()))
    for name in sorted(set(deck.main_cards())):
        if (cards.power_cost(name) or 0) != 1:
            continue
        wanted = cards.domains(name) or []
        for rune_name in runes:
            domain = (cards.domains(rune_name) or [None])[0]
            if domain and (not wanted or domain in wanted):
                return name, rune_name
    return None, runes[0] if runes else "Chaos Rune"


def engine_turn_steps(check):
    """The parts of 315-317 the table's suite pins and the engine's did not."""
    g = at_main(seed=179)
    drew = [e for e in g.log if "draw phase" in e["text"]]
    check("the Turn Player draws for turn (315.4)", bool(drew),
          drew[0]["text"] if drew else "no draw-phase entry in the log")

    g2 = at_main(seed=181)
    s2 = g2.s
    s2.energy[s2.turn_player] = 3
    s2.power[s2.turn_player] = {"Fury": 1}
    turn.enter_phase(g2, "ending")
    for _ in range(40):
        if s2.phase != "ending":
            break
        g2._tick()
    check("unspent Energy is lost at the end of the turn (317.2.e)",
          not s2.energy[0] and not s2.energy[1]
          and not s2.power[0] and not s2.power[1])

    # 117: the mulligan, one card at a time.
    g3 = game(seed=191, first=0, auto_trivial=False)
    decision = g3.step()
    seat = decision.view["seat"]
    hand_before = list(g3.s.hand[seat])
    aside = [o for o in decision.options if o.key[0] == "aside"][0]
    g3.answer(aside)
    g3.answer(g3.step().find(("keep",)))
    check("a mulligan redraws to the same hand size (117.2)",
          len(g3.s.hand[seat]) == len(hand_before))
    kept = list(hand_before)
    kept.remove(aside.key[1])
    check("the cards not set aside are still in hand (117.1)",
          all(name in g3.s.hand[seat] for name in kept))
    check("a set-aside card cannot be redrawn by the same mulligan (117.2, 117.3)",
          g3.s.hand[seat].count(aside.key[1]) == hand_before.count(aside.key[1]) - 1
          and aside.key[1] in g3.s.main_deck[seat],
          "set aside, redrawn from what was left, and only then recycled")
    check("a mulligan sets aside at most two cards (117.1)",
          raises(lambda: turn.finish_mulligan(g3, seat, list(hand_before)[:3]),
                 "at most"))

    # 431: the burn out, as a sequence rather than a log line.
    g4 = at_main(seed=193)
    s4 = g4.s
    s4.main_deck[0] = []
    s4.trash[0] = list(s4.hand[0][:1]) or ["Gust"]
    s4.hand[0] = s4.hand[0][1:]
    hand_before = len(s4.hand[0])
    actions.draw(g4, 0, 1)
    check("drawing from an empty Main Deck reports a Burn Out (431)",
          any("BURNS OUT" in e["text"] for e in g4.log))
    check("the draw that caused the burn out still completes (431.2.d, 315.4.b.2)",
          len(s4.hand[0]) == hand_before + 1)


def engine_guards(check):
    """The refusals. Each says something different, so each can be pinned apart."""
    g = at_main(seed=197)
    s = g.s
    check("a card not in the zone it is played from is refused (354)",
          raises(lambda: chain.play_card(g, 0, "A CARD NOBODY HOLDS", "hand"),
                 "is not in seat"))
    check("a card cannot be discarded from a hand that lacks it (422)",
          raises(lambda: actions.discard(g, 0, "A CARD NOBODY HOLDS"),
                 "is not in seat"))
    check("a card in no zone cannot be put into play",
          raises(lambda: actions.put_into_play(g, 0, a_unit(), loc_base(0), False,
                                               "banished"),
                 "is not in seat"))
    from_trash = a_unit()
    s.trash[0].append(from_trash)
    actions.put_into_play(g, 0, from_trash, loc_base(0), False, "trash")
    check("an effect may put a card into play from a named zone",
          from_trash not in s.trash[0]
          and any(u["name"] == from_trash for u in s.units))
    check("an unknown object id is refused, not silently ignored",
          raises(lambda: s.unit("u999"), "no object with id"))
    check("a location that is not a location is refused",
          raises(lambda: actions.move(g, s.units[0]["id"], "somewhere:3"),
                 "is not a location"))
    gear = next((n for n in sorted(set(two_decks()[0].main_cards()))
                 if turn.category(n) == "gear"), None)
    if gear is None:
        check("only units have a Standard Move (144)", False,
              "the fixture deck has no Gear to try to move")
    else:
        s.trash[0].append(gear)
        piece = actions.put_into_play(g, 0, gear, loc_base(0), False, "trash")
        check("only units have a Standard Move (144)",
              actions.standard_move_legal(s, piece, loc_bf(0))
              == "only units have a Standard Move (144)")

    check("a deck with no battlefields cannot start a game (103.4)",
          raises(lambda: turn.setup(_no_battlefields()), "no battlefields"))

    # Identity. `mint` never hands out an id already on the board.
    g2 = at_main(seed=199)
    minted = [g2.s.mint("u") for _ in range(5)]
    check("minted ids are unique among themselves", len(set(minted)) == 5)
    g2.s.next_id = 1
    taken = set(o["id"] for o in g2.s.units + g2.s.runes)
    check("minting skips an id already in use",
          g2.s.mint("r") not in taken and taken,
          "%d id(s) already on the board" % len(taken))

    # Refusing an answer must not move the position.
    g3 = at_main(seed=211)
    before = g3.s.hash()
    check("a refused answer leaves the position byte-identical",
          raises(lambda: g3.answer(("a", "move", "nobody", "offered")), "not one of")
          and g3.s.hash() == before)


def _no_battlefields():
    """A game whose seat-0 deck provides no battlefield (103.4)."""
    class _Bare(object):
        def __init__(self, deck):
            self._deck = deck
            self.chosen_champion = deck.chosen_champion
            self.name = deck.name

        def main_cards(self):
            return self._deck.main_cards()

        def rune_cards(self):
            return self._deck.rune_cards()

        def battlefield_cards(self):
            return []

    a, b = two_decks()
    return Game.new(_Bare(a), b, seed=3, first=0, hash_log=False)


def engine_privacy(check):
    """108.7.c: a hand is Private Information, in the log as well as the view."""
    g = at_main(seed=223)
    public = g.public_log()
    private = [e for e in g.log if e.get("private_to") is not None]
    check("the log still shows that a draw happened (108.7.c)",
          any("draws" in e["text"] for e in public) and private)
    drawn = set()
    for entry in private:
        drawn.update(entry["detail"].split(", "))
    check("a seat sees its own draws in full (108.7.c)",
          any(name in e["text"] for e in g.public_log(0)
              for name in g.s.hand[0] if name),
          "seat 0's own draw entries carry their detail")
    theirs = [e for e in g.public_log(0)
              if e.get("private_to") == 1]
    check("and still not the opponent's (108.7.c)",
          all("detail" not in e for e in theirs), "%d entr(ies)" % len(theirs))
    check("a finished game can be reviewed in full",
          all("detail" in e for e in g.log if e.get("private_to") is not None),
          "the record keeps what a seat view redacts")


def engine_control(check):
    """188-192 and 323.6/323.7 — who holds what, and what goes home."""
    g = _contest(seed=227)
    s = g.s
    check("moving alone onto an empty battlefield takes control and Conquers "
          "(469.1)",
          s.battlefields[0]["ctrl"] == 1 and s.points[1] >= 1
          and not s.battlefields[0]["contested"],
          "seat 1 walked in, nothing contested it back")

    g2 = at_main(seed=229)
    s2 = g2.s
    put(g2, 0, a_unit(), loc_bf(0))
    put(g2, 1, a_unit(), loc_bf(0))
    s2.battlefields[0]["contested"] = True
    s2.battlefields[0]["contested_by"] = 1
    refresh(g2)
    turn.cleanup_once(g2)
    check("a cleanup hands control to nobody while a combat is staged there "
          "(190.4.b)",
          s2.battlefields[0]["ctrl"] is None
          and s2.battlefields[0]["cb_staged"])

    g3 = at_main(seed=233)
    s3 = g3.s
    homebody = put(g3, 0, a_unit(), loc_base(0))
    standing = put(g3, 0, a_unit(), loc_bf(0))
    s3.battlefields[0]["ctrl"] = 0
    mark = len(g3.log)
    turn.run_cleanup(g3)
    swept = [e["text"] for e in g3.log[mark:] if "323.7" in e["text"]]
    check("a unit in its OWN base is left alone by the same sweep (323.7)",
          homebody["loc"] == loc_base(0)
          and not any(homebody["id"] in t for t in swept),
          "the sweep picked it up: %s" % swept)
    check("a unit at a battlefield is untouched by the Gear clause (323.7)",
          standing["loc"] == loc_bf(0))

    gear = next((n for n in sorted(set(two_decks()[0].main_cards()))
                 if turn.category(n) == "gear"), None)
    if gear is None:
        check("unattached Gear left at a battlefield is recalled at cleanup "
              "(323.7)", False, "the fixture deck has no Gear")
    else:
        s3.trash[0].append(gear)
        loose = actions.put_into_play(g3, 0, gear, loc_bf(1), False, "trash")
        turn.run_cleanup(g3)
        check("unattached Gear left at a battlefield is recalled at cleanup "
              "(323.7)", loose["loc"] == loc_base(0))


def engine_victory(check):
    """467-472 and 196 — the point, the target, and where the game stops."""
    g = at_main(seed=239)
    s = g.s
    s.battlefields[0]["ctrl"] = 0
    before = s.points[0]
    scoring.score(g, 0, 0, method="Conquer")
    check("a Score gains a point (468.1)", s.points[0] == before + 1)

    # 485.3: the Victory Score is what is in force, never the mode's default.
    g2 = at_main(seed=241)
    s2 = g2.s
    s2.victory_target = 9
    s2.points[0] = 8
    actions.check_victory(g2)
    check("a raised Victory Score is respected, not overridden by the mode's 8 "
          "(485.3)", s2.winner is None)
    s2.points[0] = 9
    actions.check_victory(g2)
    check("and the raised Victory Score still ends the game when reached (472)",
          s2.winner == 0)

    # 196: the game ends where it is won.
    g3 = at_main(seed=243)
    s3 = g3.s
    # The Scoring Step about to run is the NEXT turn's, so the battlefields have
    # to belong to the seat the turn is about to pass to.
    held = 1 - s3.turn_player
    for bf in s3.battlefields:
        bf["ctrl"] = held
        put(g3, held, a_unit(), loc_bf(bf["i"]))
    s3.points[held] = s3.victory_target - 2
    refresh(g3)
    s3.tasks = []
    turn.enter_phase(g3, "ending")
    runes_before = len([r for r in s3.runes if r["ctrl"] == held])
    hand_before = len(s3.hand[held])
    decision = g3.step()
    check("a win in the Scoring Step stops the turn where it happened (196, 472)",
          decision.terminal and s3.winner == held
          and len([r for r in s3.runes if r["ctrl"] == held]) == runes_before
          and len(s3.hand[held]) == hand_before,
          "seat %r won on %r in the %s phase" % (s3.winner, s3.points, s3.phase))
    check("a finished game asks no more questions (196)",
          g3.step().terminal and g3.s.phase == "over")


#: How many combats the parity scenarios reach. Both sides of each one assign
#: damage, so the harness must make twice this many comparisons; keying the
#: comparison on "is this the first assign_damage decision of the combat" made
#: it exactly this many, all of them the Attacker's.
_COMBATS_IN_SCENARIOS = 7

#: A floor on how many STATE comparisons the scenarios make, well under the 159
#: they make today and well over the 3 a harness that only compared final
#: positions would. The number that used to be reported was the answer count,
#: which is four times larger and measures something else.
_STATE_COMPARISON_FLOOR = 100


def engine_parity(check):
    """The table, played alongside the engine, one scripted decision at a time."""
    problems, counts = parity.run_all()
    check("the engine and the table agree on the shared subset, step for step",
          not problems, problems[0] if problems
          else "%d scripted answer(s) across %d scenario(s), %d state comparison(s), "
               "%d damage assignment(s) compared"
               % (counts["answers"], len(parity.SCENARIOS), counts["states"],
                  counts["assignments"]))
    # Three different numbers, because they measure three different things and
    # the answer count is the one that flatters. The harness reported it alone
    # and read as four times the coverage it has.
    check("and it compares a state at every Main Phase decision, not only at the "
          "end",
          counts["states"] >= _STATE_COMPARISON_FLOOR
          and counts["states"] < counts["answers"],
          "%d of %d answers are at a Main Phase decision or the end; the rest are "
          "Chain, Focus and combat-step positions the table cannot be in"
          % (counts["states"], counts["answers"]))
    check("and it compares BOTH sides' damage assignments, not just the "
          "Attacker's (465.2.c)",
          counts["assignments"] >= 2 * _COMBATS_IN_SCENARIOS,
          "%d comparison(s) over %d combat(s) — one per side"
          % (counts["assignments"], _COMBATS_IN_SCENARIOS))

    # The harness, audited: shown a difference, it must name one.
    spec = parity.SCENARIOS[0]
    keys = parity.script(spec)
    game_ = parity._engine(spec)
    game_.step()
    top = table.Table(list(fixtures.pair()), spec["seed"], first=spec["first"])
    top.setup()
    parity.transplant(top, game_.s)
    top.players[0].points += 3
    engine_side, table_side = parity.snapshot(game_.s, top)
    check("the harness compares points, zones, units, runes and battlefields",
          set(parity.RULE_FOR) <= set(engine_side),
          ", ".join(sorted(engine_side)))
    check("and a difference in any of them is a difference the harness sees",
          engine_side["points"] != table_side["points"])
    check("every field the harness compares names the rule that decides it",
          all(field in parity.RULE_FOR for field in engine_side),
          "un-named: %s" % sorted(set(engine_side) - set(parity.RULE_FOR)))

    check("every deliberate divergence from the table is named, with how the "
          "harness handles it",
          len(parity.DIVERGENCES) >= 4
          and all(len(v) > 40 for v in parity.DIVERGENCES.values()),
          "; ".join(sorted(parity.DIVERGENCES))[:100])
    check("and every verb that cannot be mapped says why",
          parity.UNMAPPED and all(len(v) > 40 for v in parity.UNMAPPED.values()),
          "%d unmapped" % len(parity.UNMAPPED))


def engine_ported(check):
    """Every check in the table's suite, classified and resolved."""
    table_names = list(TABLE_NAMES)
    missing = sorted(set(table_names) - set(ported.PORTED))
    stale = sorted(set(ported.PORTED) - set(table_names))
    check("every check in the table's suite is classified: ported, shared or not "
          "applicable",
          bool(table_names) and not missing and not stale,
          "unclassified: %s; stale: %s" % (missing[:2], stale[:2])
          if (missing or stale) else "%d check(s)" % len(table_names))

    registered = _registered_names()
    claimed = sorted(set(v for v in ported.PORTED.values()
                         if ported.classify(v) == "ported"))
    if registered is None:
        check("every ported check names an engine check that ran, by its exact "
              "name", False, "the suite's name registry is not reachable from here")
    else:
        phantom = sorted(c for c in claimed if c not in registered)
        # "ran" is not "passed", and the count below says green. A ported check
        # that is red is a table check the engine has stopped carrying, which is
        # the one thing this map exists to make impossible to miss.
        red = sorted(c for c in claimed if c in (_failed_names() or set()))
        check("every ported check names an engine check that ran, by its exact "
              "name, and passed", not phantom and not red,
              ("no such check: %s" % "; ".join(phantom[:3]) if phantom
               else "red: %s" % "; ".join(red[:3]) if red
               else "%d engine check(s) carry the table's %d"
                    % (len(claimed), sum(1 for v in ported.PORTED.values()
                                         if ported.classify(v) == "ported"))))

    excused = [v for v in ported.PORTED.values() if ported.classify(v) != "ported"]
    check("and every check that does not apply says why, in a sentence",
          all(len(v.split(":", 1)[1].strip()) > 25 for v in excused),
          "%d excused" % len(excused))

    counts = collections.Counter(ported.classify(v)
                                 for v in ported.PORTED.values())
    check("the table's suite is accounted for, check by check",
          sum(counts.values()) == len(table_names),
          "%d of %d table checks are ported and green; %d are the same code under "
          "both tools; %d do not apply. The suite's other %d checks are "
          "`proven_ratio`, which reports on this whole suite, the engine included"
          % (counts["ported"], len(table_names), counts["shared"], counts["na"],
             ported.PROVEN_RATIO_CHECKS))


#: The order is not cosmetic, and three mutants proved it. A check that only
#: runs AFTER a whole game has been played cannot be watched to fail by a defect
#: that stops a game finishing: the suite dies first, the battery records a
#: CRASH instead of a named check, and the check keeps a credit nobody earned.
#: Deleting 323.2, for instance, makes 466.3.d re-stage a combat that can never
#: resolve, and the kernel hits its spin bound inside whichever section plays a
#: game first.
#:
#: So the sections that probe a rule on a hand-built board come first, and within
#: them the ones that touch nothing but a pure function come before the ones that
#: run a Damage Step. `engine_setup` stays at the front because it is where
#: `TABLE_NAMES` is taken.
SECTIONS = (
    engine_setup, engine_cloning, engine_instruments_bite,
    engine_designations, engine_keywords, engine_assignment, engine_combat,
    engine_combat_steps, engine_decision_api,
    engine_turn, engine_turn_steps, engine_resources, engine_chain,
    engine_showdowns, engine_scoring, engine_victory, engine_movement,
    engine_control, engine_guards, engine_privacy, engine_determinization,
    engine_instruments, engine_parity, engine_primer_coverage, engine_ported,
)
