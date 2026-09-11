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
    _designations(game, bad)
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
    """A player who meets 472 never goes unnoticed.

    NOT "points never exceed the Victory Score" — they can, and the rules say
    so. 472 decides the win "when a cleanup occurs", and 315.2.b.2 Holds ALL the
    battlefields a Turn Player controls, so a player on 7 controlling both
    finishes the Scoring Step on 9. The old cap was really asserting that the
    win was decided inside the Score, which is what made the second Hold
    impossible.

    What must hold instead is that the position is never *quietly* won: if
    somebody meets 472's condition and no winner has been declared, a Cleanup
    has to be outstanding to declare it.
    """
    s = game.s
    for seat in (0, 1):
        if s.points[seat] < 0:
            bad.append("seat %d has %d points" % (seat, s.points[seat]))
    if s.winner is not None:
        return
    leader = 0 if s.points[0] >= s.points[1] else 1
    other = 1 - leader
    if s.points[leader] >= s.victory_target and s.points[leader] > s.points[other]:
        if not any(task[0] == "cleanup" for task in s.tasks):
            bad.append("seat %d meets the Victory Score at %d-%d and no Cleanup is "
                       "outstanding to notice it (472, 323.1)"
                       % (leader, s.points[leader], s.points[other]))


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
    # 312.2 lists the four moments a player receives Priority, and all of them
    # are inside a Chain or a Showdown. (The Main Phase's Priority is implicit:
    # the Turn Player is simply asked.) Priority left lying around after a window
    # closes makes one position hash two ways.
    if not s.chain and s.showdown is None and s.priority is not None:
        bad.append("seat %s still holds Priority with no Chain and no Showdown "
                   "(312.2, 313.5)" % s.priority)


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


def _designations(game, bad):
    """323.2: during a Combat every Unit's designation agrees with its controller.

    The whole of combat reads sides by designation and not by who is standing
    where (465.2.a-b), so a unit that slipped past 323.2 does not crash anything
    — it silently stops being in the combat, and its Might stops counting. And
    outside a Combat nothing may carry a designation at all, because 466.7.a
    removes them and a leftover one would make the next combat's Assault live
    for a unit that is not attacking.
    """
    s = game.s
    if s.combat_attacker is None:
        stray = [u["id"] for u in s.units if u["role"] is not None]
        if stray:
            bad.append("%s still carry an Attacker/Defender designation with no Combat "
                       "in progress (466.7.a)" % ", ".join(sorted(stray)))
        return
    if s.showdown is None:
        bad.append("a Combat has an Attacker (seat %s) but no Showdown to be part of "
                   "(464.2)" % s.combat_attacker)
        return
    here = "%s:%d" % ("bf", s.showdown["bf"])
    for unit in s.units:
        if not unit["unit"]:
            continue
        want = None
        if unit["loc"] == here:
            want = "attacker" if unit["ctrl"] == s.combat_attacker else "defender"
        if unit["role"] != want:
            bad.append("%s [%s] is designated %r and 323.2 says it should be %r"
                       % (unit["name"], unit["id"], unit["role"], want))


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
