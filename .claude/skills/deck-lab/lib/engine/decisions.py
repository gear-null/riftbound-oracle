"""The decision-request API — the one interface every player of this game uses.

    game = Game.new(deck_a, deck_b, seed)
    while True:
        d = game.step()          # run the rules until a choice is needed
        if d.terminal:
            break
        game.answer(policy[d.seat](d))

Three properties are load-bearing and this module exists to hold them still,
because later slices (search, evaluation, the LLM bridge) are all written
against this shape:

1. **Legal options are generated, never validated.** `Decision.options` is the
   complete list. `Game.answer` refuses anything that is not in it, so a policy
   cannot play an illegal move even by accident, and a bug in option generation
   surfaces as a missing move rather than as an illegal game.

2. **Compound choices are grouped, not multiplied.** "Play Stellacorn Herder at
   bf:1" is two consecutive decisions — which card, then where — not one option
   in a product of cards x locations. The product is what makes a branching
   factor explode; grouping is the approach Forge and the LoCM agents both
   settled on.

3. **Every option has a stable hashable key and a human-readable label.** The
   key is a tuple of primitives, so it can be a dict key in a search table, be
   written into a golden file, and be compared across runs. The label is for
   people and never for code.
"""

#: Every kind of choice this API will ever emit. Fixed here on purpose: the
#: interface is the thing later slices build on, so the vocabulary is declared
#: whole and the ones this slice does not yet produce say so.
#:
#: Emitted by the vanilla kernel:
#:   mulligan          set a card aside, or keep (117)
#:   main              a Discretionary Action in a Neutral Open Main Phase (316.5)
#:   chain             respond or pass — the Execute step of FEPR (338.1), and
#:                     the act-or-pass window of a Showdown (347). `view["window"]`
#:                     says which; both are "the player on turn to act may play
#:                     something legally timed or pass".
#:   target            the second half of a grouped choice: where a Unit enters
#:                     (355.2), where a Unit Moves (144.4), which staged
#:                     Showdown or Combat the Turn Player opens (323.12, 323.13)
#:
#: Emitted once an ability is attached (issue #24). A vanilla game still never
#: produces one, because a vanilla card has no abilities — which is why the
#: check on `EMITTED` plays a vanilla game and a second check plays one with
#: `engine/demo.py`'s abilities attached:
#:   optional          a "you may" as the first part of a Triggered Ability's
#:                     effect, decided during finalization (383.3.a, 402.1), and
#:                     a "may apply" on a Replacement Effect (371.2)
#:   order             which of several simultaneously triggered abilities goes
#:                     on the Chain next (383.3.d), asked one at a time; across
#:                     seats the order is Turn Order and not a choice (383.3.d.1,
#:                     303.2.a)
#:   cost              declining to pay for a Triggered Ability that incurred one
#:                     (404.2), and "unless [a player] pays" asked of that seat
#:                     on resolution (355.10.c.1)
#:   assign_damage     which unit takes the next combat damage assignment
#:                     (465.2.c) — asked one target at a time, because lethal
#:                     goes on in full before the next unit (465.2.c.3) and the
#:                     product of whole assignments is what explodes
#:
#: Declared, NOT YET EMITTED. Each is wired to a named gap in
#: docs/engine/spec.md:
#:   modal             "choose one -" on a card (355.3)
#:   resolve_manually  the bridge to the table: a card with no accepted script
#:                     is applied by hand and the log says so (ADR 0009)
KINDS = (
    "mulligan", "main", "chain", "target",
    "modal", "optional", "order", "assign_damage", "cost", "resolve_manually",
)

#: The kinds this slice can actually produce. `selftest` asserts that nothing
#: outside this set is ever emitted, so the day a later slice starts emitting
#: `modal` it has to move the name and say so. `assign_damage` joined it with
#: issue #23: a combat with two units on a side has more than one legal
#: assignment, and which one is chosen decides who lives. `optional`, `order`
#: and `cost` joined it with issue #24, which is the slice that made abilities
#: real — and a name in this tuple is a claim, so `engine_abilities` asserts
#: each of the three is actually produced rather than merely permitted.
EMITTED = ("mulligan", "main", "chain", "target", "assign_damage",
           "optional", "order", "cost")


class Option:
    """One legal choice: a stable key, and a label for a person.

    Equality and hashing are by key alone. A policy may return the Option, the
    key, or the index — `Game.answer` accepts all three and refuses the rest.
    """

    __slots__ = ("key", "label")

    def __init__(self, key, label):
        self.key = key
        self.label = label

    def __eq__(self, other):
        return self.key == getattr(other, "key", other)

    def __hash__(self):
        return hash(self.key)

    def __repr__(self):
        return "Option(%r, %r)" % (self.key, self.label)


class Decision:
    """A question the rules have reached, and every legal answer to it.

    `view` is the asking seat's INFORMATION SET, not the game state: its own
    hand, every public zone, and the sizes of the hidden ones. A policy that
    reads only `view` cannot cheat; `Game.state` is there for search, which is
    expected to determinize with `apply_seed` rather than to peek.
    """

    __slots__ = ("seat", "kind", "options", "view", "terminal", "prompt")

    def __init__(self, seat, kind, options, view, prompt="", terminal=False):
        self.seat = seat
        self.kind = kind
        self.options = options
        self.view = view
        self.prompt = prompt
        self.terminal = terminal

    def keys(self):
        return [o.key for o in self.options]

    def find(self, answer):
        """The Option matching `answer`, or None. Never guesses."""
        if isinstance(answer, Option):
            answer = answer.key
        if isinstance(answer, int) and not isinstance(answer, bool):
            return self.options[answer] if 0 <= answer < len(self.options) else None
        if isinstance(answer, list):
            answer = tuple(answer)
        for option in self.options:
            # Through `Option.__eq__`, which compares by key and accepts a bare
            # key on the right. Comparing `option.key == answer` here worked and
            # left the operator dead — defined, never called, and impossible to
            # watch fail.
            if option == answer:
                return option
        return None

    def __repr__(self):
        if self.terminal:
            return "Decision(terminal)"
        return "Decision(seat=%s, kind=%s, %d options)" % (
            self.seat, self.kind, len(self.options))


def terminal(view):
    """The decision that is not a decision: the game is over."""
    return Decision(None, "main", [], view, prompt="the game is over", terminal=True)
