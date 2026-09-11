"""Combat (459-466) — the minimal three steps, enough for a game to end.

Issue #23 does rigorous combat: designations per unit, the FEPR windows between
the Resolution Step's sub-steps, Mighty and bonus damage, damage-assignment
decisions. This slice does the part a vanilla game needs, and
`docs/engine/spec.md` lists what is simplified so the gap is a written one rather
than a discovered one:

* The **Combat Showdown Step** (464) is real: the Attacker is the player whose
  unit applied Contested (464.2.c.1), that player takes Focus, and the
  alternating window runs through `chain.py` like any other Showdown.
* The **Damage Step** (465) sums Might and assigns lethal-first, which is the
  table's ported assignment. The assignment is computed, not chosen — the
  `assign_damage` decision kind exists and is not yet emitted.
* The **Resolution Step** (466) runs as one Task rather than as three with a
  FEPR window between each, because no vanilla item can be put on the Chain
  between them.
"""
from . import scoring
from .state import RulesError, loc_bf


def attacker_at(s, bf):
    """The Attacker: whoever's unit applied Contested (464.2.c.1).

    Assuming the Turn Player is wrong in both directions. A non-turn player can
    contest — a unit becoming present during a Showdown does it — and the
    designation decides which side 466.1.a.2 recalls, so getting it backwards
    loses a battlefield its controller was holding.
    """
    if bf["contested_by"] is None:
        raise RulesError("%s has no recorded Attacker — nothing applied Contested to "
                         "it (464.2.c.1)" % bf["name"])
    return bf["contested_by"]


def assign_damage(s, attackers, defenders):
    """A legal damage assignment from one side onto the other (465.2.c).

    Lethal-first, and never more than the minimum lethal amount on a unit while
    another unit is still undamaged (465.2.c.3, 465.2.c.4). Returns
    {unit id: damage}. The order within the constraint is the assigning player's
    choice; this returns one legal ordering.
    """
    pool = sum(s.might_of(u) for u in attackers)
    assignment = {}
    for target in defenders:
        if pool <= 0:
            break
        # 142.4.b: lethal is a NON-ZERO amount equalling or exceeding Might, so
        # the minimum lethal assignment for a 0-Might unit is 1, not 0. Treating
        # it as 0 assigns nothing, walks past a unit that could still legally be
        # assigned damage, and dumps the excess on the last defender — which
        # 465.2.c.3 and 465.2.c.4 both forbid.
        might = s.might_of(target)
        already_lethal = target["dmg"] > 0 and target["dmg"] >= might
        need = 0 if already_lethal else max(might - target["dmg"], 1)
        give = min(pool, need)
        if give:
            assignment[target["id"]] = give
        pool -= give
    # 465.2.c.4: more than the minimum lethal is allowed only once no further
    # unit remains to be assigned damage — i.e. every defender already has its
    # full lethal, which is the only way `pool` survives the loop.
    if pool > 0 and defenders:
        last = defenders[-1]["id"]
        assignment[last] = assignment.get(last, 0) + pool
    return assignment


def damage_step(g, index):
    """465: sum Might, assign starting with the Attacker, deal simultaneously."""
    s = g.s
    bf = s.battlefield(index)
    location = loc_bf(index)
    attacker = attacker_at(s, bf)
    defender = 1 - attacker
    attackers = s.units_at(location, attacker)
    defenders = s.units_at(location, defender)

    # 465.1: the step runs only if both sides still have units here.
    if not attackers or not defenders:
        g.note("no damage at %s — one side has no units left (465.1)" % bf["name"])
        return

    a_might = sum(s.might_of(u) for u in attackers)
    d_might = sum(s.might_of(u) for u in defenders)
    g.note("combat at %s: seat %d %d Might vs seat %d %d Might (465.2.a-b)"
           % (bf["name"], attacker, a_might, defender, d_might))

    # 465.2.c.1.a: damage is ASSIGNED by each side and then DEALT
    # simultaneously, so both assignments are computed before either is applied.
    onto_defenders = assign_damage(s, attackers, defenders)
    onto_attackers = assign_damage(s, defenders, attackers)
    for oid, amount in sorted(onto_defenders.items()) + sorted(onto_attackers.items()):
        if amount:
            unit = s.unit(oid)
            unit["dmg"] += amount
            g.note("  %s [%s] takes %d damage (%d/%d)"
                   % (unit["name"], oid, amount, unit["dmg"], s.might_of(unit)),
                   seat=unit["ctrl"])
    # 465.3: skip the FEPR process and cancel any outstanding tasks; proceed to
    # the Resolution Step. Killing the dead is 323.5, and happens in the Combat
    # Cleanup that opens that step.


def resolution_step(g, index):
    """466: the Combat Cleanup, the result, Control, and the end of combat."""
    s = g.s
    bf = s.battlefield(index)
    location = loc_bf(index)

    # 466.1's Combat Special Cleanup ran as the Task queued before this one —
    # it is the one that healed every unit (3c) and recalled the Attackers if
    # any Defender survived (3d), and it sets `combat_recalled` so this step can
    # tell a repel from a rout.
    remaining = s.units_at(location)
    seats = set(u["ctrl"] for u in remaining)

    # 466.3: determine the result.
    if s.combat_recalled:
        result = "no result — attackers were repelled (466.3.d)"
    elif len(seats) == 1:
        result = "seat %d wins the combat (466.3.a)" % next(iter(seats))
    else:
        result = "no result (466.3.d)"
    g.note("combat result at %s: %s" % (bf["name"], result))

    # 466.3.d.1: both sides still present after No Result re-stages the fight.
    # Unreachable in the vanilla slice — 3d recalls every attacker when any
    # defender survives — and kept because the day a card prevents the recall it
    # is the difference between a re-staged combat and a silently lost one.
    if len(seats) == 2:
        bf["sd_staged"] = True
        bf["cb_staged"] = True

    # 466.5: with nothing staged here, whoever has units left Establishes
    # Control. This runs whether or not the attackers were repelled: a defender
    # who has just held off an attack, and who may not have controlled the
    # battlefield before it, takes it.
    if not (bf["sd_staged"] or bf["cb_staged"]):
        if len(seats) == 1:
            winner = next(iter(seats))
            if bf["ctrl"] != winner:
                scoring.establish_control(g, winner, index)
        bf["contested"] = False        # 466.5.a
        bf["contested_by"] = None
        if not remaining and bf["ctrl"] is not None:
            g.note("%s becomes uncontrolled (466.5.b)" % bf["name"])
            bf["ctrl"] = None

    # 466.7: combat ends. 466.7.a removes the Attacker and Defender designations
    # from all units and players, which here is the Showdown record going away.
    g.note("combat at %s ends (466.7)" % bf["name"])
    s.showdown = None
    s.combat_recalled = False
    g.status_changed()
