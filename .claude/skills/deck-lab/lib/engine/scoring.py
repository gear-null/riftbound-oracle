"""Scoring (467-472) and Control of Battlefields (188-192).

Two rules here are the ones a game played by hand loses points to, and both are
ported from the table with the reasoning that put them there:

* **Hold happens in the Beginning Phase and nowhere else** (469.2). A Hold
  awarded at any other time is a point the rules never grant.
* **The final point has a condition** (471.1.b.1). A Conquer that would take a
  player to the Victory Score only does so if they have Scored EVERY battlefield
  this turn; otherwise they draw a card and the game goes on. Skipping it ends
  games one point early, which is invisible in a log and fatal to a win rate.
"""
from . import abilities, actions
from .state import RulesError


def score(g, seat, index, method="Conquer"):
    """Score a battlefield for seat, if they have not already scored it (470)."""
    s = g.s
    bf = s.battlefield(index)
    if method == "Hold" and s.phase != "beginning":
        raise RulesError("a Hold is scored during the Beginning Phase, not %s (469.2)"
                         % s.phase)
    if seat in bf["scored"]:
        raise RulesError("seat %d already scored %s this turn — once per battlefield "
                         "per turn (470)" % (seat, bf["name"]))
    bf["scored"].append(seat)
    target = s.victory_target

    # 471.1.b: a Conquer that would take a player to the Victory Score only does
    # so if they scored EVERY battlefield this turn; otherwise they draw.
    # 471.1.a.1 exempts points gained from anything that is not a Conquer, which
    # is why a Hold at 7 takes the game.
    if method == "Conquer" and s.points[seat] >= target - 1:
        if all(seat in b["scored"] for b in s.battlefields):
            s.points[seat] += 1
            g.note("seat %d takes the FINAL POINT at %s -> %d (471.1.b.1)"
                   % (seat, bf["name"], s.points[seat]), seat=seat)
        else:
            g.note("seat %d conquers %s but has not scored every battlefield this turn "
                   "— draws a card instead of the final point (471.1.b.1)"
                   % (seat, bf["name"]), seat=seat)
            actions.draw(g, seat, 1, reason="final point denied")
            # 471.2 and 383.4.c.2.c: the Score happened, so the Score
            # abilities trigger — only the point was withheld. "If the act of
            # gaining one point from Conquering is negated or replaced in any
            # way, the Conquer Effect will still trigger."
            _score_triggers(g, seat, index, method)
            return s.points[seat]
    else:
        s.points[seat] += 1
        g.note("seat %d SCORES %s by %s -> %d point(s)"
               % (seat, bf["name"], method, s.points[seat]), seat=seat)

    _score_triggers(g, seat, index, method)

    # No victory check here. 472 says a player wins "when a cleanup occurs" —
    # and one always follows, because a Score changes the board. Deciding it
    # inside the Score instead made 315.2.b.2 unfinishable: a Turn Player on 7
    # controlling both battlefields would win on the first Hold and never take
    # the second, which is a Score the rules say happens.
    return s.points[seat]


def _score_triggers(g, seat, index, method):
    """471.2: trigger Score abilities AT THE BATTLEFIELD that Scored.

    383.4.c.2 and 383.4.d.2 each split the same event two ways: the abilities of
    UNITS that were present when the battlefield was scored, and the abilities
    of anything that references the PLAYER who scored. One event carries both —
    `loc` is what a unit's `where` matches on, `seat` is what a "when you
    conquer" listens for — so the listener decides, not the emitter.
    """
    from .state import loc_bf
    bf = g.s.battlefield(index)
    # Two literal emits, for the reason `combat._designation_trigger` gives: an
    # event name built at runtime cannot be found by the check that asserts
    # every declared trigger event has somewhere that raises it.
    if method == "Conquer":
        abilities.emit(g, "conquer", seat=seat, loc=loc_bf(index), bf=index,
                       name=bf["name"])
    else:
        abilities.emit(g, "hold", seat=seat, loc=loc_bf(index), bf=index,
                       name=bf["name"])


def establish_control(g, seat, index):
    """Give seat Control of a battlefield, Conquering it if not yet scored.

    466.5.d and 348.2.a both end here, and both say the same thing: establishing
    Control is a Conquer if that player has not yet scored this battlefield this
    turn (469.1).
    """
    s = g.s
    bf = s.battlefield(index)
    was = bf["ctrl"]
    bf["contested"] = False
    bf["contested_by"] = None
    bf["ctrl"] = seat
    g.note("seat %d establishes control of %s" % (seat, bf["name"]), seat=seat)
    g.status_changed()
    if was != seat and seat not in bf["scored"]:
        score(g, seat, index, method="Conquer")
    return bf


def hold_all(g, seat):
    """315.2.b: the Turn Player Holds all Battlefields they Control.

    Iterated in battlefield order, which is turn order at setup (the first
    player's battlefield is index 0) — so this loop is the same loop in a
    mirrored game.
    """
    for bf in list(g.s.battlefields):
        if bf["ctrl"] == seat and seat not in bf["scored"]:
            score(g, seat, bf["i"], method="Hold")
    # ALL of them, with no early exit. 472 decides the win at the cleanup that
    # follows this step, not partway through it, so a player who passes the
    # Victory Score on the first Hold still takes the second — and may finish on
    # more points than the Victory Score, which is a state the rules allow and
    # `invariants._points` now expects.
