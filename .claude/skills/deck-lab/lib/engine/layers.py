"""Layers (473-480) — what a Game Object's traits actually are.

475.1 says layers "only serve to structure the application and order that Game
Effects apply". That is exactly what this module is: a **recomputation**, not a
sequence of mutations. Nothing anywhere writes `unit["mod"]` or `unit["kw"]`; a
game effect creates a continuous effect and `recompute` derives every affected
trait from the whole set, in the order 477 gives, every time.

Three properties are load-bearing:

* **Order is the CR's, never the script's.** A +2 Might written above a
  "set Might to 1" on a card still applies after it, because 477.1.a.1 puts the
  assignment in layer 1 and 477.3 puts the arithmetic in layer 3. A framework
  that applies effects as it meets them gets this backwards and produces a
  plausible number.
* **A passive's contribution is re-derived, never stored.** `s.effects` holds
  only what a RESOLUTION created (a "+2 Might this turn"). What a passive
  ability contributes is asked for again on every recomputation, which is what
  makes a keyword gate (727) continuous: the turn its condition stops holding,
  the contribution is simply not offered and the trait goes back.
* **It is a fixpoint** (476.2). Effects whose scope depends on a trait another
  effect changes settle by recurring the whole sequence, bounded so a pair that
  fights forever is a named failure rather than a hang.

A **buff is not here.** 702 makes it a counter on the unit and 703 gives each
one +1 Might; it survives "this turn" expiry and goes away only when the unit
leaves play (705). `give_might` is a layer-3 continuous effect with a duration.
Both raise Might and they are different objects, and the pair is the reason this
module and `actions.buff` are separate things.
"""
from .state import RulesError

#: 477's three layers, in the order it lists them. The numbers are the rule's.
TRAITS, ABILITIES, ARITHMETIC = 1, 2, 3
LAYERS = (TRAITS, ABILITIES, ARITHMETIC)

#: Which layer each operation belongs to. Read out of 477, not chosen: a table
#: means an operation whose layer nobody looked up is a KeyError here rather
#: than an effect that quietly lands in whichever layer the author assumed.
LAYER_OF = {
    #: 477.1.a.1 — "Assignment of Might is dealt with in this layer."
    "set_might": TRAITS,
    #: 477.1.a — Controller is a trait.
    "set_controller": TRAITS,
    #: 477.2.a — granting a keyword is an ability-altering effect.
    "grant": ABILITIES,
    #: 477.2.a — removing rules text.
    "remove": ABILITIES,
    #: 477.2.a — granting a whole ability, by registry key.
    "grant_ability": ABILITIES,
    #: 477.3.a — the mathematics of Might.
    "give_might": ARITHMETIC,
}

#: Durations a STORED effect may carry (census §5b / the DSL's `DURATIONS`).
#: `while_state` is deliberately absent: the DSL's own note says a gated
#: ability's `while_state` takes its state from the gate, and a gated passive is
#: re-derived every recomputation, so the duration has nothing left to express.
DURATIONS = ("this_turn", "permanent", "this_combat", "until_event")

#: 476.2 recurs the sequence until nothing changes. A bound, for the same reason
#: 322's cleanup loop has one: two effects that disqualify each other would
#: otherwise spin, and a hang is a bug nobody can find.
MAX_PASSES = 16


def new_effect(g, op, **fields):
    """Create a continuous effect and give it a Timestamp (480.1).

    Returns the effect dict, already on `s.effects`. Every caller goes through
    here so that no effect can exist without a layer and a timestamp — a layer
    decided at application time is a layer that depends on the order things were
    applied, which is the thing 475.1 exists to remove.
    """
    s = g.s
    if op not in LAYER_OF:
        raise RulesError("%r is not a layer operation (477)" % (op,))
    until = fields.get("until", "permanent")
    if until not in DURATIONS:
        raise RulesError("%r is not a duration this framework carries (477.3, "
                         "census 5b)" % (until,))
    s.stamp += 1
    effect = {
        "id": "e%d" % s.stamp,
        "ts": s.stamp,
        "layer": LAYER_OF[op],
        "op": op,
        "n": 0,
        "kw": "",
        "src": "",
        "ctrl": None,
        "targets": (),
        "until": until,
        "ev": "",
    }
    effect.update(fields)
    effect["targets"] = tuple(effect["targets"])
    s.effects.append(effect)
    recompute(g)
    return effect


def expire(g, duration, event=""):
    """Remove every stored effect whose window has closed. True if any went.

    317.2.d ("all 'this turn' effects expire") and 466.7 are the two windows the
    kernel closes on its own; `until_event` closes when the named event is
    emitted, which is what makes "until end of combat" and "until it leaves"
    expressible without a second mechanism.
    """
    s = g.s
    gone = [e for e in s.effects
            if e["until"] == duration
            and (duration != "until_event" or e["ev"] == event)]
    if not gone:
        return False
    for effect in gone:
        s.effects.remove(effect)
        # 480.2: text that stops applying loses its Timestamp. A stored effect
        # is removed outright, so there is nothing to un-stamp; the entry that
        # matters is a passive's, and `recompute` drops that below.
    g.note("%d continuous effect(s) expire: %s (477, 317.2.d)"
           % (len(gone), duration))
    recompute(g)
    return True


def effects_on(s, oid):
    """Every stored effect currently applying to one object. For the log."""
    return [e for e in s.effects if oid in e["targets"]]


# -- the recomputation ---------------------------------------------------

def recompute(g):
    """476: apply each effect once, and recur until nothing more can apply.

    The three sentences of 476 are each load-bearing and each easy to get wrong:

    * 476: "applied repeatedly until all effects operating on objects have been
      applied once and no changes have been processed" — so the traits are reset
      ONCE, at the start, and the sequence then accumulates.
    * 476.1: "each effect ... applied as soon as able, and only a single time
      across all sequences". An effect whose scope is empty is not yet able, and
      one that has applied never applies again — which is also 477.3.b's
      snapshotting: what it selected when it applied is what it keeps.
    * 476.2: "when a sequence of applications completes, recur the process, and
      evaluate each layer again applying any effects that may now be
      applicable". That recursion is the whole point: a layer-2 grant whose
      condition a layer-3 effect makes true applies on the SECOND sequence.

    Returns the number of sequences it took. The selftest reads it, because a
    rule that settles in one sequence and one that settles in three are
    different rules and the count is the only way to watch the recursion happen.
    """
    from . import abilities
    s = g.s
    _reset(s)
    if not s.effects and not abilities.REGISTRY:
        # Nothing can contribute, so the printed traits are the answer and one
        # sequence reaches it. The fast path exists because this runs at every
        # 319 board change, and a vanilla game has thousands of those.
        return 1
    applied = set()
    # Each sequence applies at least one effect or stops, so the number of
    # sequences cannot exceed the number of effects plus one. The bound is
    # therefore a guard on 476.1's apply-once rather than on the rules: if it
    # ever fires, something is applying an effect twice.
    bound = max(MAX_PASSES, len(s.effects) + 2)
    for n in range(bound):
        progress = False
        for layer in LAYERS:
            pool = [e for e in _all_effects(g)
                    if e["layer"] == layer and e["id"] not in applied]
            for effect in _ordered(pool, layer):
                targets = [u for u in s.units if u["id"] in effect["targets"]]
                if not targets:
                    continue                       # 476.1: not yet able
                for unit in targets:
                    _apply(unit, effect)
                applied.add(effect["id"])
                progress = True
        if not progress:
            return n + 1
    raise RulesError("the layers ran %d sequences and never ran out of effects "
                     "to apply — something is applying twice (476.1)" % bound)


def _derived(s):
    """The fields the layers own, as one comparable tuple."""
    return tuple((u["id"], u["setm"], u["mod"], u["kw"], u["ctrl"])
                 for u in s.units)


def _reset(s):
    """Back to the printed traits, before any layer has applied.

    Control resets to the OWNER and not to whatever it currently is: 477.1.a
    makes Controller a trait this layer alters, and a trait that a
    recomputation cannot put back is a trait whose effect can never end.
    """
    for unit in s.units:
        unit["setm"] = None
        unit["mod"] = 0
        unit["kw"] = ()
        unit["ctrl"] = unit["owner"]


def _all_effects(g):
    """Stored effects, plus what every ACTIVE passive contributes right now.

    The second half is re-derived per pass on purpose (see the module
    docstring): a passive whose gate has closed simply stops offering anything,
    with no separate removal step to forget to run.
    """
    from . import abilities
    return list(g.s.effects) + abilities.passive_effects(g)


def _ordered(effects, layer):
    """One layer's effects, in Timestamp order (480.3), increases before decreases.

    478/479's Dependency is a declared gap and 476.2 is why it is a small one:
    the scope of an effect that has not applied yet is recomputed on every
    sequence, so an effect whose set of objects another effect widens picks the
    wider set up on the next sequence — which is the outcome 479.2 prescribes
    for the reachable cases. Where the two genuinely differ is an effect that
    the other DISQUALIFIES; `docs/engine/spec.md` names that as the gap.
    """
    if layer == ARITHMETIC:
        # 477.3.e: increases first (477.3.e.1), decreases last (477.3.e.2).
        # Within each half, Timestamp order (480.3). Sorting by (sign, ts) in
        # one pass is the same walk and keeps the two rules in one place.
        return sorted(effects, key=lambda e: (0 if e["n"] >= 0 else 1, e["ts"]))
    return sorted(effects, key=lambda e: e["ts"])


def _apply(unit, effect):
    op = effect["op"]
    if op == "set_might":
        unit["setm"] = effect["n"]
    elif op == "give_might":
        unit["mod"] += effect["n"]
    elif op == "set_controller":
        unit["ctrl"] = effect["n"]
    elif op == "grant":
        unit["kw"] = tuple(sorted(unit["kw"] + ((effect["kw"], effect["n"] or 1),)))
    elif op == "remove":
        unit["kw"] = tuple(k for k in unit["kw"] if k[0] != effect["kw"])
    elif op == "grant_ability":
        # Carried on the unit as a keyword-shaped marker so `abilities.on_object`
        # can find it without a second per-unit field. The value is the index
        # into the registry entry named by `kw`.
        unit["kw"] = tuple(sorted(unit["kw"] + (("ability:" + effect["kw"],
                                                 effect["n"]),)))
    else:
        raise RulesError("no layer rule for %r (477)" % (op,))


# -- reading the result --------------------------------------------------

def has_keyword(unit, keyword):
    """Does this unit have `keyword`, printed or granted (477.2)?

    The printed side reads the unit's own field, because 807.2/814.2/826 all
    make a granted instance ADD to the printed one rather than replace it.
    """
    from .state import granted
    printed = unit.get(keyword)
    if isinstance(printed, bool):
        return printed or granted(unit, keyword) > 0
    return (printed or 0) + granted(unit, keyword) > 0


def keyword_value(unit, keyword):
    """The total value of a numeric keyword: printed plus every granted one."""
    from .state import granted
    printed = unit.get(keyword) or 0
    if isinstance(printed, bool):
        printed = 1 if printed else 0
    return printed + granted(unit, keyword)


def granted_abilities(unit):
    """The registry keys of abilities granted to this unit (477.2.a)."""
    out = []
    for name, value in unit["kw"]:
        if name.startswith("ability:"):
            out.append((name[len("ability:"):], value))
    return out
