"""Conservation invariants, checked on every transition.

Chess engines call these "sanity bitboards" and run them in debug builds: cheap
properties that no legal sequence of moves can break, asserted after every
single one. They catch the class of bug that a win rate cannot — a card that
exists in two places, a point that appeared from nowhere, a chain that resolved
out of order — because those produce a plausible game rather than a crash, and a
plausible game is exactly what a deck verdict is computed from.

`Game.new(..., invariants=True)` runs `check` after every mandatory operation.
That is slow, so it is off by default and on in the selftest, in the golden
replays, and in a sampled fraction of the soak.
"""
import collections

from .state import BASE, is_bf


def check(game):
    """Every violation, as a list of strings. Empty means the position is legal."""
    s = game.s
    bad = []
    _cards_conserved(game, bad)
    _points(game, bad)
    _one_zone(game, bad)
    _chain_order(game, bad)
    _locations(game, bad)
    _turn_state(game, bad)
    return bad


def assert_ok(game, where=""):
    bad = check(game)
    if bad:
        from .state import RulesError
        raise RulesError("invariant broken%s: %s"
                         % (" after %s" % where if where else "", "; ".join(bad)))


def _cards_conserved(game, bad):
    """Every card a seat brought is in exactly one of that seat's zones.

    The Main Deck pool and the Rune Deck pool are counted separately, because
    416 sends a recycled rune to the RUNE deck and a recycled card to the Main
    Deck — a single pool would hide a rune that came back as a spell.
    """
    s = game.s
    for seat in (0, 1):
        deck = game.decks[seat]
        expected = collections.Counter(deck.main_cards())
        if deck.chosen_champion:
            expected[deck.chosen_champion] += 1
        found = collections.Counter()
        found.update(s.hand[seat])
        found.update(s.main_deck[seat])
        found.update(s.trash[seat])
        found.update(s.banished[seat])
        found.update(s.champion[seat])
        found.update(u["name"] for u in s.units if u["owner"] == seat)
        found.update(c["name"] for c in s.chain if c["ctrl"] == seat)
        if found != expected:
            missing = expected - found
            extra = found - expected
            bad.append("seat %d's Main Deck cards are not conserved (missing %s, extra %s)"
                       % (seat, dict(missing), dict(extra)))

        runes_expected = collections.Counter(deck.rune_cards())
        runes_found = collections.Counter(s.rune_deck[seat])
        runes_found.update(r["name"] for r in s.runes if r["ctrl"] == seat)
        if runes_found != runes_expected:
            bad.append("seat %d's runes are not conserved (missing %s, extra %s)"
                       % (seat, dict(runes_expected - runes_found),
                          dict(runes_found - runes_expected)))


def _points(game, bad):
    """Points only ever go up, and never past the Victory Score.

    The cap holds because 303.2 forbids simultaneous actions: every gain is
    checked against 472 before the next one happens, so the first player to
    reach the target has strictly more than the other and wins there. A score of
    9, or a tie at 8, means something gained a point without the check running.
    """
    s = game.s
    for seat in (0, 1):
        if s.points[seat] < 0:
            bad.append("seat %d has %d points" % (seat, s.points[seat]))
        if s.points[seat] > s.victory_target:
            bad.append("seat %d is past the Victory Score at %d points without the game "
                       "having ended (472)" % (seat, s.points[seat]))
    if s.winner is None and min(s.points) >= s.victory_target:
        bad.append("both seats are at the Victory Score and nobody has won (472)")


def _one_zone(game, bad):
    """No object is in two places, and no id answers for two objects."""
    s = game.s
    ids = [o["id"] for o in s.units] + [r["id"] for r in s.runes] \
        + [c["id"] for c in s.chain]
    if len(ids) != len(set(ids)):
        seen = collections.Counter(ids)
        bad.append("duplicate object id(s): %s"
                   % sorted(k for k, n in seen.items() if n > 1))


def _chain_order(game, bad):
    """The Chain is a stack, and pending items are always the newest on it.

    337.1 finalizes the OLDEST pending item and 340.1 resolves the NEWEST
    finalized one, so a finalized item can never sit above a pending one. If it
    does, the next resolution takes the wrong item and the Chain has stopped
    being LIFO.
    """
    s = game.s
    seen_pending = False
    for item in s.chain:
        if item["pending"]:
            seen_pending = True
        elif seen_pending:
            bad.append("the Chain has a finalized item above a pending one — it is no "
                       "longer LIFO (337.1, 340.1)")
            break


def _locations(game, bad):
    """Every permanent is somewhere the board has."""
    s = game.s
    for unit in s.units:
        kind, _, idx = unit["loc"].partition(":")
        if kind == BASE and idx in ("0", "1"):
            continue
        if is_bf(unit["loc"]) and 0 <= int(idx) < len(s.battlefields):
            continue
        bad.append("%s [%s] is at %r, which is not a location"
                   % (unit["name"], unit["id"], unit["loc"]))


def _turn_state(game, bad):
    """307-310: the turn is always in exactly one of the four combined states."""
    s = game.s
    if s.showdown is not None:
        bf = s.showdown["bf"]
        if not (0 <= bf < len(s.battlefields)):
            bad.append("a Showdown is ongoing at battlefield %r" % (bf,))
        elif s.showdown["focus"] not in (0, 1):
            bad.append("a Showdown has no player with Focus (313)")
    if s.is_showdown() and not s.is_closed() and s.turn_state() != "showdown-open":
        bad.append("the four states of 310 disagree with the board")
