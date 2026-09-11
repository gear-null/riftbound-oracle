"""Replacement Effects (367-375) — the six shapes the gauntlet actually prints.

The census counted them before any of this was written: 59 of 389 gauntlet cards
(15%) carry one, over six kinds — `cost_replacement` (19 cards),
`enters_modified` (17), `instead` (15), `ignoring_cost` (8), `would` (7) and
`as_enters` (3). So this is not general machinery for a rule nobody uses; it is
six shapes, and two of them are not interception at all:

* **`cost_replacement` and `ignoring_cost` are arithmetic**, done inside the cost
  calculation (356.1.b, 356.3, 356.4). They never see an event.
* **`enters_modified` and `as_enters` are the entry itself** — 369.3 identifies
  them by "describing how the unit enters, or by describing a game action that
  occurs 'as' a unit enters", and 370.1.b.1 says the "as" shape is the event
  PLUS the action rather than a substitution.
* **Only `instead` and `would` intercept**, and they are 22 clauses across 16
  cards.

The two rules that make the pipeline correct rather than merely present:

* **Once per event** (370.2). A Replacement Effect applies once to an event, and
  once to anything that replaces it — so a "would die -> return to hand instead"
  cannot loop against itself, and the record of what has applied is carried
  through the replacements, not reset with each one.
* **Can't beats can** (054.1). A Replacement Effect that forbids supersedes one
  that permits the same thing, whatever the timestamps say.
"""
from . import abilities
from .state import RulesError

#: The events a Replacement Effect may intercept in this slice. Closed on
#: purpose: an event named here is one some call site actually raises, and one
#: that is not is a refusal rather than a replacement that silently never fires.
EVENTS = ("enter", "die", "damage", "draw", "gain_point")

#: 370.1.b lets a replacement replace an event with further events, which can
#: themselves be replaced. A bound, because a pair that replaces each other's
#: output forever is a bug and a hang is the worst way to report one.
MAX_REPLACEMENTS = 32


def apply(g, event):
    """367-375. Returns the event to perform, or None if it was replaced away.

    370.1.c: applied BEFORE the qualifying event has actually occurred, which is
    why every call site builds the event and asks here first rather than doing
    the thing and patching it up.
    """
    if event["ev"] not in EVENTS:
        raise RulesError("%r is not a replaceable event (370.1.a)" % (event["ev"],))
    if not abilities.REGISTRY:
        return event
    applied = set()
    for _ in range(MAX_REPLACEMENTS):
        candidates = _qualifying(g, event, applied)
        if not candidates:
            return event
        src = candidates[0]
        applied.add(src["key"])
        _count(g, src)
        g.note("  %s replaces the %s (%s)"
               % (src["name"], event["ev"],
                  "054.1, can't beats can" if src["ab"].forbids else "370.1.b"),
               seat=src["seat"])
        event = src["ab"].replace(g, event, src)
        if event is None:
            return None
    raise RulesError("replacement effects replaced each other %d times without "
                     "settling (370.1.b)" % MAX_REPLACEMENTS)


def _qualifying(g, event, applied):
    """Every Replacement Effect that may apply to this event, best first.

    The order is 054 first, then 373.1's turn order across controllers, then
    480.3's Timestamp within one. `docs/engine/spec.md` records what is NOT
    here: 372's "the controller of the object being acted on determines the
    order" is not asked as a decision, because a replacement is applied inside a
    mandatory operation that the decision API cannot suspend partway through.
    """
    s = g.s
    order = list(s.turn_order())
    out = []
    for src in abilities.sources(g, kinds=("instead", "would", "enters_modified",
                                           "as_enters")):
        ability = src["ab"]
        if src["key"] in applied:
            continue                                       # 370.2
        if not abilities.active(g, src):
            continue                                       # 721.2
        if not _frequency_ok(g, src):
            continue                                       # 371.1
        if ability.applies is None or not ability.applies(g, event, src):
            continue                                       # 370.1
        out.append(src)
    out.sort(key=lambda x: (0 if x["ab"].forbids else 1,
                            order.index(x["seat"]) if x["seat"] in order else 9,
                            _stamp(g, x)))
    return out


def _stamp(g, src):
    key = "%s#%s#%d" % (src["oid"], src["key"][0], src["key"][1])
    return g.s.stamps.get(key, 0)


def _freq_key(src):
    """371.1's counter, kept apart from 383.3.e's by the leading R.

    One object can carry a triggered ability and a replacement that both say
    "once each turn", and a shared key would have either one spend the other's
    allowance.
    """
    ability = src["ab"]
    return "R|%s|%s|%d|%s" % (src["oid"], ability.owner, ability.index,
                              ability.frequency[2])


def _frequency_ok(g, src):
    """371.1: "once each turn" caps how many EVENTS it may be applied to."""
    if src["ab"].frequency is None:
        return True
    _kind, n, _per = src["ab"].frequency
    return g.s.used.get(_freq_key(src), 0) < n


def _count(g, src):
    if src["ab"].frequency is None:
        return
    key = _freq_key(src)
    g.s.used[key] = g.s.used.get(key, 0) + 1


# -- costs (356.1.b, 356.3, 356.4, 366.2) --------------------------------

def cost_modifiers(g, seat, name):
    """What `cost_replacement` and `ignoring_cost` do to one card's cost.

    Returns (ignore_energy, ignore_power, d_energy, d_power), applied by
    `actions.total_cost` in the order 356 gives: 356.1.b zeroes a base cost
    first, then 356.3's increases and 356.4's discounts are arithmetic on what
    is left.

    A `cost_replacement` returns which COMPONENT it moves and by how much, and
    356.4.c is the reason it is not one number: a discount that applies to a
    component is applied when that component is added, before any discount that
    applies to the total, so an engine that folds Energy and Power into one
    delta cannot express either rule.

    366.2.a is why these abilities are found in a HAND at all: a passive that
    alters the cost of cards as they are played "applies at all times in any
    zone from which the card with the ability can be played".
    """
    ignore_energy = ignore_power = False
    d_energy = d_power = 0
    if not abilities.REGISTRY:
        return ignore_energy, ignore_power, d_energy, d_power
    event = {"ev": "cost", "name": name, "seat": seat}
    for src in abilities.sources(g, kinds=("cost_replacement", "ignoring_cost")):
        ability = src["ab"]
        if not abilities.active(g, src):
            continue
        if ability.applies is None or not ability.applies(g, event, src):
            continue
        if ability.kind == "ignoring_cost":
            # 356.1.b.1: "ignoring its cost" sets base Energy AND Power to zero;
            # 356.1.b.2: naming one of them sets only that one.
            which = ability.replace(g, event, src)
            ignore_energy = ignore_energy or which in ("energy", "all")
            ignore_power = ignore_power or which in ("power", "all")
        else:
            component, amount = ability.replace(g, event, src)
            if component == "power":
                d_power += amount
            else:
                d_energy += amount
    return ignore_energy, ignore_power, d_energy, d_power
