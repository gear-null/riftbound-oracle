"""The decks every engine fixture is built from, named once, in one place.

Tournament lists come and go with the meta. The gauntlet is refreshed on its own
cadence (`docs/maintaining.md`), and a list that was the best Annie deck in one
pull is a duplicate to be deleted in the next. A fixture that names one is a
test that breaks for a reason which has nothing to do with the engine — and it
does not break loudly: a golden file, a perft board and a selftest fixture all
naming the same removed slug fail six frames down inside `deckfile.resolve`,
three separate times, saying nothing about the actual cause.

So the fixtures name the **core-meta** lists, which exist in the gauntlet
precisely to be stable, and they name them HERE. Everything else — the perft
boards, the golden playthroughs, the selftest's own decks — imports from this
module, so a list that has to change is one edit and one regeneration rather
than a search.

`engine_setup` asserts that each of these still resolves to a legal deck, so the
day one is renamed the suite says which fixture deck is gone, by name.
"""
import deckfile

#: Irelia: a board deck with cheap units. The default seat-0 fixture, because
#: the shapes most of these checks need — a unit to move, a battlefield to
#: contest — are the shapes this deck makes on its own.
IRELIA = "irelia-core-meta"
#: Viktor: the default opponent, and a different archetype, so a check that only
#: passes in a mirror does not pass here.
VIKTOR = "viktor-core-meta"
#: Kennen: the third deck, for anything that has to be told apart from the first
#: two — the "a seat's shuffle does not depend on the opposing deck" check, and
#: the perft board and golden game that must not reuse the default pair.
KENNEN = "kennen-tempest-meta"

#: Every fixture deck, for the check that they all still exist.
ALL = (IRELIA, VIKTOR, KENNEN)


def deck(slug):
    """One fixture deck, resolved."""
    return deckfile.resolve(slug)


def pair():
    """The default fixture pair: seat 0 and seat 1."""
    return deck(IRELIA), deck(VIKTOR)


def missing():
    """Which fixture decks no longer resolve to a legal deck. Empty is correct."""
    gone = []
    for slug in ALL:
        try:
            result = deckfile.check(deck(slug))
        except (KeyError, FileNotFoundError, ValueError) as err:
            gone.append("%s: %s" % (slug, err))
            continue
        if not result.legal:
            gone.append("%s: %s" % (slug, "; ".join(result.errors[:2])))
    return gone
