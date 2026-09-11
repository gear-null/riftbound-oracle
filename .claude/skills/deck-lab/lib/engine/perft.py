"""Legal-action perft — the move generator's own test, borrowed from chess.

perft(d) counts the leaves of the decision tree d decisions deep from a fixed
board. It tests nothing about whether the engine plays well and everything about
whether it enumerates the right moves: add an illegal option, drop a legal one,
or let a rule fire at the wrong moment and the count moves. Chess engines have
used it for forty years because a single integer per depth catches move
generation bugs that a thousand games will not.

Two things make it work here:

* **The boards are canonical and seeded.** A board is a deck pair, a seed, a
  first player and a fixed number of decisions taken by a named policy, so
  `board("midgame")` is the same position on every machine and in every release.
* **`divide` bisects a mismatch.** When perft(3) disagrees with its golden,
  `divide` prints perft(2) under each root option, so the wrong subtree is one
  command away instead of a bisect through the rules.

Chance is not a branch. The shuffle is already fixed by the seed, so the tree
counted here is the DECISION tree, not the game tree — which is the number a
policy's branching factor actually faces.
"""
from . import fixtures, policies
from .game import Game

#: Three canonical boards. `advance` decisions are taken by a seeded random
#: policy first, which is how a midgame position becomes reproducible without
#: anyone having to write one down.
BOARDS = {
    "opening": {
        "a": fixtures.IRELIA, "b": fixtures.VIKTOR,
        "seed": 7, "first": 0, "advance": 0, "policy": 101,
    },
    "midgame": {
        "a": fixtures.IRELIA, "b": fixtures.VIKTOR,
        "seed": 11, "first": 1, "advance": 24, "policy": 202,
    },
    # Chosen to earn its name: both battlefields are controlled and units are
    # deployed at them, so the option generator is exercised on moves home,
    # moves in, and plays to a held battlefield — none of which the other two
    # boards reach. A board called "contested" that is not contested is a
    # fixture lying about what it covers.
    "contested": {
        "a": fixtures.VIKTOR, "b": fixtures.KENNEN,
        "seed": 5, "first": 0, "advance": 36, "policy": 303,
    },
}


def board(name):
    """The named canonical board, as a Game stopped on its next decision."""
    spec = BOARDS[name]
    game = Game.new(fixtures.deck(spec["a"]), fixtures.deck(spec["b"]),
                    seed=spec["seed"], first=spec["first"], hash_log=False)
    pol = policies.random_pair(spec["policy"])
    for _ in range(spec["advance"]):
        decision = game.step()
        if decision.terminal:
            break
        game.answer(pol[decision.seat](decision))
    return game


def perft(game, depth):
    """Leaves of the decision tree `depth` decisions deep.

    A game that ends before the depth is reached counts as one leaf and is not
    expanded — the same convention chess uses for checkmate.
    """
    decision = game.step()
    if decision.terminal or depth <= 0:
        return 1
    total = 0
    for option in decision.options:
        child = game.clone()
        child.answer(option.key)
        total += perft(child, depth - 1)
    return total


def divide(game, depth):
    """perft(depth-1) under each option at the root. Returns [(label, key, n)]."""
    decision = game.step()
    if decision.terminal or depth <= 0:
        return []
    out = []
    for option in decision.options:
        child = game.clone()
        child.answer(option.key)
        out.append((option.label, option.key, perft(child, depth - 1)))
    return out


def counts(name, max_depth=3):
    """perft(1..max_depth) from a named board."""
    return [perft(board(name), d) for d in range(1, max_depth + 1)]
