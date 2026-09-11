"""Hand-built abilities, attached to real fixture cards.

No card text is parsed in this slice (that is the interpreter, issue #26), so the
ability framework is exercised the way ADR 0009 says it will be exercised until
then: with abilities written by hand. These are NOT the cards' printed
abilities — they are fixtures — and the docstring of each one says which rule it
is there to make reachable.

Two jobs:

* **the soak.** `python3 deck_cli.py engine soak --abilities` plays a thousand
  random games with these attached, and every one still has to end by a named
  rule. A framework that deadlocks, loops or leaves a Pending Item on the Chain
  shows up here and nowhere else, because nothing else plays whole games with
  triggers in them.
* **a worked example.** Each is roughly the shape a compiled script will have:
  a kind, a gate, a trigger, a cost and a callable, with the callable being the
  only part the interpreter will replace.

`attach()` and `detach()` are a matched pair and every caller uses them in a
`try/finally`. The registry is module-global card data (see `abilities.py`), so
a test that leaves its fixtures behind changes every game that runs after it —
which is exactly how a perft golden moves for no reason anybody can name.
"""
from . import abilities, actions, layers

#: The fixture cards these hang on. Named here rather than inline so that a
#: gauntlet rename breaks `engine_setup`'s deck check with a sentence, the same
#: way `fixtures.ALL` does.
CARDS = (
    "Scuttle Crab", "Tideturner", "Stellacorn Herder", "Pyke - Returned",
    "Carrion Dredger", "Honest Broker", "Card Sharp", "Akali, Silent",
)

_ATTACHED = []


# -- the effects ---------------------------------------------------------

def _gain_xp(g, ctx):
    actions.gain_xp(g, ctx["seat"], 1)


def _self_might(g, src):
    """A passive contribution: +1 Might to the unit that has it (477.3)."""
    return [{"op": "give_might", "n": 1, "targets": (src["oid"],)}]


def _owner_gains_xp(g, ctx):
    actions.gain_xp(g, ctx["seat"], 1)


def _delayed_xp(g, ctx):
    """Create the Delayed Ability. 392: it fires whether I am still here or not."""
    abilities.delay(g, ctx["seat"], ("Honest Broker", 1), "end_of_turn",
                    window="this_turn", src_id=ctx["src"]["oid"])


def _enters_ready(g, event, src):
    """369.3: describing HOW it enters. 359.2.c's exhausted becomes ready."""
    event["exh"] = False
    return event


def _enters_applies(g, event, src):
    return event.get("name") == src["name"] and event.get("seat") == src["seat"]


def _cheaper(g, event, src):
    """356.4.b: "costs 1 less". A component discount, so it names the component."""
    return ("energy", -1)


def _cheaper_applies(g, event, src):
    from . import turn
    return (event.get("seat") == src["seat"]
            and turn.category(event.get("name", "")) == "spell")


def _soften(g, event, src):
    """369: "would be dealt damage" — the event, with one less on it."""
    event["n"] = max(event["n"] - 1, 0)
    return event


def _soften_applies(g, event, src):
    return event.get("oid") == src["oid"]


# -- the fixture set -----------------------------------------------------

def build():
    """The abilities, as (card name, [Ability, ...]) pairs."""
    return [
        # 383.4.a: a Play Effect, with 383.3.a's "you may" — the `optional`
        # decision, asked at finalization and removing the item if declined.
        ("Scuttle Crab", [
            abilities.Ability(
                "triggered", text="when you play me, you may gain 1 XP",
                cite="CR:383.4.a", optional=True,
                trigger=abilities.Trigger(("play_self",), who="me"),
                effect=_gain_xp),
        ]),
        # 727/812: a Dependent Keyword gating a Passive. Inactive until you have
        # finalized another card this turn, and Inactive again next turn.
        ("Tideturner", [
            abilities.Ability(
                "passive", text="[Legion] I have +1 Might",
                cite="CR:812", gate=abilities.Gate("Legion"),
                modifier=_self_might),
        ]),
        # 376-381: an Activated Ability with an exhaust cost, offered in the
        # Main Phase and nowhere else (381).
        ("Stellacorn Herder", [
            abilities.Ability(
                "activated", text="[E]: gain 1 XP", cite="CR:377",
                cost=abilities.Cost(exhaust_self=True), effect=_gain_xp),
        ]),
        # 808/383.2.c.1: a trigger that fires from an object that has already
        # left the Board.
        ("Pyke - Returned", [
            abilities.Ability(
                "triggered", text="[Deathknell] gain 1 XP", cite="CR:808",
                trigger=abilities.Trigger(("die",), who="me"),
                effect=_owner_gains_xp),
        ]),
        # 367/369.3: the commonest replacement shape in the gauntlet.
        ("Carrion Dredger", [
            abilities.Ability(
                "enters_modified", text="I enter ready", cite="CR:367",
                applies=_enters_applies, replace=_enters_ready),
        ]),
        # 383.4.c + 389-392: a Conquer Effect whose effect CREATES a Delayed
        # Ability (index 1). 392 is the half worth watching in a real game: the
        # delayed half fires at end of turn whether or not Honest Broker is
        # still on the board.
        ("Honest Broker", [
            abilities.Ability(
                "triggered", text="when you conquer, gain 1 XP at end of turn",
                cite="CR:383.4.c",
                trigger=abilities.Trigger(("conquer",), who="you"),
                effect=_delayed_xp),
            abilities.Ability(
                "delayed", text="at the end of this turn, gain 1 XP",
                cite="CR:389",
                trigger=abilities.Trigger(("end_of_turn",), who="any"),
                effect=_gain_xp),
        ]),
        # 366.2.a + 356.4: a cost replacement, which functions from the BOARD
        # over cards played from a hand.
        ("Card Sharp", [
            abilities.Ability(
                "cost_replacement", text="your spells cost 1 less Energy",
                cite="CR:367", applies=_cheaper_applies, replace=_cheaper),
        ]),
        # 369 + 371.1: a `would` replacement with a once-each-turn limit.
        ("Akali, Silent", [
            abilities.Ability(
                "would", text="once each turn, damage dealt to me is 1 less",
                cite="CR:369", applies=_soften_applies, replace=_soften,
                frequency=("limit", 1, "turn")),
        ]),
    ]


def attach():
    """Register the fixture abilities. Returns the names touched."""
    for name, abils in build():
        abilities.register(name, *abils)
        _ATTACHED.append(name)
    return list(_ATTACHED)


def detach():
    """Take them all off again. Always in a `finally`."""
    for name in _ATTACHED:
        abilities.REGISTRY.pop(name, None)
    del _ATTACHED[:]


def missing(decks):
    """Which fixture cards these abilities name are not in `decks` any more.

    Empty is correct. A demo ability on a card no deck plays is a fixture that
    proves nothing while reporting that it does — the same failure `fixtures.missing`
    exists to catch one level up.
    """
    pool = set()
    for deck in decks:
        pool.update(deck.main_cards())
        if deck.chosen_champion:
            pool.add(deck.chosen_champion)
    return [name for name in CARDS if name not in pool]


def relayer(g):
    """Recompute the layers. For tests that build a board by hand."""
    return layers.recompute(g)
