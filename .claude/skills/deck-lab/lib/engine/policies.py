"""Policies — the clients of the decision-request API this slice ships.

Both are deterministic, and both are per seat. Per seat matters more than it
looks: a policy whose stream is shared between the two seats makes seat 0's
choices depend on how many questions seat 1 was asked, and the perfect-symmetry
test then fails for a reason that is in the harness rather than in the engine.

Neither of these plays well. Playing well is issue #24 onwards (greedy, then
beam + PIMC); what these are for is running the rules over and over until
something breaks.
"""
from . import rng


class RandomPolicy:
    """Uniform over the legal options, from one seat's own stream."""

    __slots__ = ("state", "seed")

    def __init__(self, seed):
        self.seed = seed
        self.state = rng.seed_from(seed)

    def __call__(self, decision):
        self.state, i = rng.below(self.state, len(decision.options))
        return decision.options[i]


class FirstOption:
    """Always the first legal option. Deterministic with no state at all.

    The option lists are ordered plays, then moves, then "end the turn", so this
    is a policy that always does something rather than one that passes the game
    away — which makes it a far better probe: a game where nobody ever acts
    exercises the turn loop and nothing else.
    """

    __slots__ = ()

    def __call__(self, decision):
        return decision.options[0]


class ContentPolicy:
    """Deterministic in WHAT is asked, not in how many questions came before.

    `RandomPolicy` advances a stream per answer, so a game that asks one extra
    question answers everything after it differently. That makes it useless for
    comparing a game against the same game with the one-option decisions
    surfaced — the comparison would fail for the harness's reasons rather than
    the engine's. This one hashes the decision itself, so the same question
    always gets the same answer however it was reached.
    """

    __slots__ = ()

    def __call__(self, decision):
        key = repr((decision.seat, decision.kind, [o.key for o in decision.options]))
        return decision.options[rng.seed_from(key) % len(decision.options)]


class ScriptedPolicy:
    """Replays a recorded list of option keys, and refuses to improvise.

    This is what makes a golden game a test rather than a recording: the script
    is the answer to every decision in order, and a kernel that asks a DIFFERENT
    question — or asks one more, or one fewer — fails here instead of quietly
    producing a different game.
    """

    __slots__ = ("keys", "at")

    def __init__(self, keys):
        self.keys = [tuple(k) for k in keys]
        self.at = 0

    def __call__(self, decision):
        if self.at >= len(self.keys):
            raise AssertionError("the script ran out at decision %d (%s)"
                                 % (self.at, decision.prompt))
        key = self.keys[self.at]
        self.at += 1
        option = decision.find(key)
        if option is None:
            raise AssertionError(
                "decision %d: the script answers %r, which is not among %s"
                % (self.at - 1, key, [o.key for o in decision.options]))
        return option


def play(game, policies, limit=200000):
    """Run a game to its end. Returns the game.

    `limit` is a bound on decisions, not on turns: a kernel that asks the same
    question forever would otherwise hang CI rather than fail it.
    """
    for _ in range(limit):
        decision = game.step()
        if decision.terminal:
            return game
        game.answer(policies[decision.seat](decision))
    raise AssertionError("the game asked %d decisions without ending" % limit)


def random_pair(seed):
    """Two independent random policies, one per seat."""
    return [RandomPolicy("%s/p0" % seed), RandomPolicy("%s/p1" % seed)]
