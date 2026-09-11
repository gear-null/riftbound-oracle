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
from . import actions
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
            # 471.2: the Score happened, so the battlefield's Score abilities
            # would trigger — only the point was withheld. Vanilla battlefields
            # have no abilities in this slice (see docs/engine/spec.md).
            return s.points[seat]
    else:
        s.points[seat] += 1
        g.note("seat %d SCORES %s by %s -> %d point(s)"
               % (seat, bf["name"], method, s.points[seat]), seat=seat)

    actions.check_victory(g, "472")
    return s.points[seat]


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
            if g.s.winner is not None:
                # 196: when a player wins the game ends; it does not finish the
                # step. Scoring the second battlefield after the first one won
                # leaves a final state that never legally existed.
                return
