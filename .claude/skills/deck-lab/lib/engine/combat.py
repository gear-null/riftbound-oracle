"""Combat (459-466) — the three steps, the designations, and the assignment.

Combat is where games are decided, so this module implements the rules it cannot
yet reach as well as the ones it can. Three shapes carry the weight:

* **Designations are per unit, not per side** (464.2.c.3, 323.2). The Attacker is
  whoever's unit applied Contested (464.2.c.1) — not the Turn Player, in either
  direction — and every Unit at the battlefield carries its controller's
  designation for as long as the Combat lasts. Nothing here reads a side by
  "whose units are standing where": 465.2.a-b sum the units that HAVE the
  designation, which is what makes 323.2 load-bearing rather than decorative.
  It is also what Assault and Shield are conditional on (807.1.d, 814.1.d).

* **The assignment is a decision, not a computation** (465.2.c). More than one
  assignment is usually legal, and which one a player picks decides who lives.
  It is asked one target at a time — "which unit takes the next assignment" —
  because that is both the grouping the decision API requires (`decisions.py`,
  property 2) and the shape the rule itself has: lethal in full before moving on
  (465.2.c.3), never more than the minimum while another unit is still owed
  damage (465.2.c.4). The engine's own lethal-first assignment is
  `assign_damage`, and it is always the FIRST option, so a policy that takes the
  first option plays exactly it.

* **The Resolution Step is three Tasks with a window between each** (466.2,
  466.4, 466.6), not one. Nothing vanilla can put an item on the Chain between
  them, but the windows are real: `fepr_window` drains the Chain if there is
  anything on it, and `engine_combat` puts something there to watch it happen.
"""
from . import chain, scoring
from .decisions import Option
from .state import RulesError, loc_bf

#: The Tasks that make up Combat once it has opened. 465.3 cancels every
#: outstanding Task that is NOT one of these.
COMBAT_TASKS = ("combat_damage", "combat_fepr", "combat_result",
                "combat_control", "combat_end")


# -- designations (464.2.c, 323.2, 466.7.a) ------------------------------

def attacker_at(s, bf):
    """The Attacker: whoever's unit applied Contested (464.2.c.1).

    Assuming the Turn Player is wrong in both directions. A non-turn player can
    contest — a unit becoming present during a Showdown does it — and the
    designation decides which side 466.1.a.2 recalls, so getting it backwards
    loses a battlefield its controller was holding.

    Once Combat has opened the designation is its own fact and is read from
    there. 466.5.a clears Contested one step BEFORE 466.7.a removes the
    designations, so for that step the battlefield no longer remembers who
    attacked and the designation still has to.
    """
    if s.combat_attacker is not None:
        return s.combat_attacker
    if bf["contested_by"] is None:
        raise RulesError("%s has no recorded Attacker — nothing applied Contested to "
                         "it (464.2.c.1)" % bf["name"])
    return bf["contested_by"]


def designate(g, index):
    """464.2.c: establish Attacker and Defender, and designate every Unit here.

    464.2.c.3 designates the PLAYERS and then the Units at the Contested
    Battlefield controlled by either of them. Units that become present later
    are picked up by 323.2.a in the next Cleanup, which is 464.2.c.3.a.
    """
    s = g.s
    bf = s.battlefield(index)
    if bf["contested_by"] is None:
        raise RulesError("%s has no recorded Attacker — nothing applied Contested to "
                         "it (464.2.c.1)" % bf["name"])
    s.combat_attacker = bf["contested_by"]
    apply_designations(g)
    g.note("seat %d is the Attacker and seat %d the Defender at %s; their units here "
           "are designated (464.2.c.1, 464.2.c.2, 464.2.c.3)"
           % (s.combat_attacker, 1 - s.combat_attacker, bf["name"]))


def apply_designations(g):
    """323.2: give every Unit the designation its controller has, or none.

    All three sub-clauses are one loop, because they are one rule read three
    ways: a Unit here without a designation gains its controller's (323.2.a), a
    Unit here with the wrong one swaps (323.2.b), and a Unit anywhere else loses
    what it has (323.2.c). Returns True if anything moved, so the Cleanup that
    calls it knows whether the state settled (322).
    """
    s = g.s
    if s.combat_attacker is None or s.showdown is None:
        return False
    location = loc_bf(s.showdown["bf"])
    changed = False
    for unit in s.units:
        if not unit["unit"]:
            continue                                   # 323.2 designates Units
        if unit["loc"] == location:
            want = "attacker" if unit["ctrl"] == s.combat_attacker else "defender"
        else:
            want = None                                # 323.2.c
        if unit["role"] != want:
            unit["role"] = want
            changed = True
    return changed


def strip_designations(g):
    """466.7.a: remove the Attacker and Defender designation from all Units and
    Players."""
    s = g.s
    for unit in s.units:
        unit["role"] = None
    s.combat_attacker = None


def attacking_units(s, index):
    """The Attacking Units at a battlefield — by designation, not by side.

    465.2.a says "all Attacking Units", and an Attacking Unit is one holding the
    Attacker designation (464.2.c.3). Selecting by controller instead gives the
    same answer today and makes 323.2 dead code: a unit that walked in
    mid-combat would fight without ever being designated, and Assault would not
    apply to it.
    """
    location = loc_bf(index)
    return [u for u in s.units
            if u["unit"] and u["loc"] == location and u["role"] == "attacker"]


def defending_units(s, index):
    """465.2.b's "all Defending Units", read the same way."""
    location = loc_bf(index)
    return [u for u in s.units
            if u["unit"] and u["loc"] == location and u["role"] == "defender"]


# -- damage assignment (465.2.c, 142.4.b, 712-715, 815, 826) -------------

def bonus_damage(units):
    """712-715: the Bonus Damage a side's Deal action carries.

    714 sums every granted instance and applies the sum ONCE; 714.1 and 714.2
    make a negative total no bonus at all rather than a reduction. It lands on
    the assignment rather than on the dealt amount because 465.2.c.5 says
    anything that would modify the resulting damage applies to the assignment
    instead, and 715 applies it to the total the action distributes.
    """
    return max(sum(u["bonus"] for u in units), 0)


def damage_pool(s, units):
    """What a side assigns: its summed Might (465.2.a-b) plus 712's bonus."""
    return sum(s.might_of(u) for u in units) + bonus_damage(units)


def minimum_lethal(s, unit, already=0):
    """142.4.b: the least damage that would be lethal, given what is marked.

    Lethal Damage is a NON-ZERO amount equalling or exceeding the unit's Might,
    so the minimum for a 0-Might unit is 1 and not 0. Reading it as 0 assigns
    nothing, walks past a unit that could still legally be assigned damage, and
    dumps the excess on the last one — which 465.2.c.3 and 465.2.c.4 both forbid.
    Returns 0 for a unit that already has lethal damage on it.
    """
    marked = unit["dmg"] + already
    might = s.might_of(unit)
    if marked > 0 and marked >= might:
        return 0
    return max(might - marked, 1)


def pending_targets(s, targets, assignment):
    """The units that may still legally be assigned damage (465.2.c.4)."""
    return [u for u in targets if minimum_lethal(s, u, assignment.get(u["id"], 0))]


def eligible_targets(s, targets, assignment):
    """Which of the pending units this player may assign to NEXT.

    815.1.c.2 makes every unit without Tank an invalid assignment until each
    Tank has its lethal; 826.4.b makes every unit with Backline invalid until
    each unit without it has. 465.2.c.7 then says units sharing a priority may
    be taken in any order, which is why this returns a LIST and every member of
    it becomes an option, rather than the code picking one.

    A unit carrying both keywords has two exclusionary requirements and 465.2.c.8
    hands the assigning player the choice of which to apply. That choice is not
    modelled: Tank wins, and `docs/engine/spec.md` records the gap.
    """
    pending = pending_targets(s, targets, assignment)
    tanks = [u for u in pending if u["tank"]]
    if tanks:
        return tanks
    plain = [u for u in pending if not u["backline"]]
    return plain if plain else pending


def next_amount(s, targets, assignment, target, pool):
    """How much `target` takes if it is chosen now (465.2.c.3, 465.2.c.4).

    Its minimum lethal — or the whole remaining pool, once no further unit
    remains to have damage assigned to it, which is the one case 465.2.c.4
    allows more than the minimum.
    """
    pending = pending_targets(s, targets, assignment)
    need = minimum_lethal(s, target, assignment.get(target["id"], 0))
    if len(pending) <= 1:
        return pool
    return min(pool, need)


def assign_damage(s, attackers, defenders):
    """The engine's own legal assignment from one side onto the other (465.2.c).

    Lethal-first, minimum-lethal, Tank before plain before Backline, and the
    excess on the last unit standing. Returns {unit id: damage}. This is ONE
    legal ordering — 465.2.c.7 allows others — and it is the one the first
    option of every `assign_damage` decision reproduces, so a policy that always
    takes the first option plays exactly this.
    """
    pool = damage_pool(s, attackers)
    assignment = {}
    while pool > 0:
        targets = eligible_targets(s, defenders, assignment)
        if not targets:
            break
        target = targets[0]
        give = next_amount(s, defenders, assignment, target, pool)
        if give <= 0:
            break
        assignment[target["id"]] = assignment.get(target["id"], 0) + give
        pool -= give
    return assignment


def validate_assignment(s, attackers, defenders, assignment):
    """Every way `assignment` breaks 465.2.c, named with the rule that says so.

    Generation already refuses an illegal assignment — the options ARE the legal
    moves — so this exists for the answers generation does not produce: a search
    writing an assignment straight into the state, a card script handing one
    over, the parity harness replaying the table's. 465.2.c.6 makes obeying the
    restrictions mandatory, so an assignment that fails here is not a choice.

    The assignment arrives as a {id: amount} map, which has lost the ORDER it
    was made in — so what is checked is whether some legal order produces it.
    That is exactly four properties: the whole pool is spent while anything can
    still take damage; at most one unit ends up short of lethal (the one the
    pool ran out on); more than the minimum lands on a unit only when nothing
    else is left to take any; and the Tank/Backline priorities were respected.
    """
    bad = []
    ids = set(u["id"] for u in defenders)
    for oid, amount in sorted(assignment.items()):
        if oid not in ids:
            bad.append("%s is not a unit on the other side of this combat (465.2.c)"
                       % oid)
        elif amount <= 0:
            bad.append("%s is assigned %d, and an assignment is a positive amount "
                       "(465.2.c)" % (oid, amount))
    if bad:
        return bad

    pool = damage_pool(s, attackers)
    total = sum(assignment.values())
    if total > pool:
        bad.append("%d damage assigned from a summed Might of %d (465.2.a-c)"
                   % (total, pool))
    def got(unit):
        return assignment.get(unit["id"], 0)

    lethal = dict((u["id"], minimum_lethal(s, u)) for u in defenders)
    short = [u for u in defenders if 0 < got(u) < lethal[u["id"]]]
    untouched = [u for u in defenders if lethal[u["id"]] and not got(u)]
    over = [u for u in defenders if lethal[u["id"]] and got(u) > lethal[u["id"]]]

    # 465.2.c: the whole summed Might is assigned. Stopping early is only legal
    # once nothing on the other side can be assigned any more damage.
    if total < pool and pending_targets(s, defenders, assignment):
        bad.append("%d of %d damage was assigned while a unit could still take some "
                   "(465.2.c, 465.2.c.6)" % (total, pool))
    # 465.2.c.3: lethal in full before the next unit. Two units left short means
    # the assignment moved on from one of them before it was finished.
    if len(short) > 1:
        bad.append("%s are each left short of lethal, so damage moved on from one "
                   "of them before it was assigned in full (465.2.c.3)"
                   % ", ".join(u["id"] for u in short))
    # 465.2.c.4: more than the minimum lethal, while something else could still
    # have been assigned damage.
    if over and (short or untouched):
        bad.append("%s has more than the minimum lethal while %d unit(s) remain to "
                   "have damage assigned (465.2.c.4)"
                   % (", ".join(u["id"] for u in over), len(short) + len(untouched)))

    # 815.1.c.2 / 826.4.b: the ordering keywords are restrictions on assignment,
    # and 465.2.c.6 makes obeying them mandatory. Both read the same way — until
    # every unit in the higher priority has its lethal, every unit outside it is
    # an invalid assignment.
    def jumped(priority, others, rule):
        if all(got(u) >= lethal[u["id"]] for u in priority):
            return
        taken = sorted(u["id"] for u in others if got(u))
        if taken:
            bad.append("%s was assigned damage before every %s"
                       % (", ".join(taken), rule))

    live = [u for u in defenders if lethal[u["id"]]]
    jumped([u for u in live if u["tank"]], [u for u in live if not u["tank"]],
           "Tank had its lethal (815.1.c.2)")
    jumped([u for u in live if not u["backline"]], [u for u in live if u["backline"]],
           "unit without Backline had its lethal (826.4.b)")
    return bad


# -- Step 2: the Combat Damage Step (465) --------------------------------

def damage_step(g, index):
    """465: sum Might, assign starting with the Attacker, deal simultaneously."""
    s = g.s
    bf = s.battlefield(index)
    attackers = attacking_units(s, index)
    defenders = defending_units(s, index)

    # 465.1: the step's Tasks become Outstanding only if both Attacking and
    # Defending units remain here.
    if not attackers or not defenders:
        g.note("no damage at %s — one side has no units left (465.1)" % bf["name"])
        return

    a_pool = damage_pool(s, attackers)
    d_pool = damage_pool(s, defenders)
    g.note("combat at %s: seat %d %d Might vs seat %d %d Might (465.2.a-b)"
           % (bf["name"], s.combat_attacker, a_pool, 1 - s.combat_attacker, d_pool))

    # 465.2.c: starting with the Attacker, each player assigns their summed
    # Might among the other's units. 465.2.c.1.a: nothing is DEALT until both
    # assignments are complete, so the state carries the first one while the
    # second is being made.
    s.choosing = {"what": "assign_damage", "bf": index,
                  "attacker": s.combat_attacker, "by": s.combat_attacker,
                  "pool": a_pool, "onto": [], "first": None}
    ask_assignment(g)


def ask_assignment(g):
    """465.2.c: which unit takes the next assignment. Asked, never assumed."""
    s = g.s
    c = s.choosing
    seat = c["by"]
    index = c["bf"]
    victims = (defending_units(s, index) if seat == c["attacker"]
               else attacking_units(s, index))
    assignment = dict(c["onto"])
    targets = eligible_targets(s, victims, assignment) if c["pool"] > 0 else []
    if not targets:
        assignment_done(g)
        return
    options = []
    for unit in targets:
        amount = next_amount(s, victims, assignment, unit, c["pool"])
        options.append(Option(("hit", unit["id"], amount),
                              "assign %d to %s [%s] (%d Might, %d marked)"
                              % (amount, unit["name"], unit["id"],
                                 s.might_of(unit), unit["dmg"])))
    g.ask(seat, "assign_damage", options,
          prompt="seat %d assigns %d more damage at %s (465.2.c)"
                 % (seat, c["pool"], s.battlefield(index)["name"]))


def apply_assignment(g, key):
    """Take one option from an `assign_damage` decision."""
    c = g.s.choosing
    c["onto"] = c["onto"] + [(key[1], key[2])]
    c["pool"] -= key[2]
    ask_assignment(g)


def assignment_done(g):
    """This player has finished assigning. The other goes next, or damage lands."""
    s = g.s
    c = s.choosing
    index = c["bf"]
    if c["by"] == c["attacker"]:
        attackers = attacking_units(s, index)
        defenders = defending_units(s, index)
        refuse_illegal(s, attackers, defenders, dict(c["onto"]))
        c["first"] = c["onto"]
        c["by"] = 1 - c["attacker"]
        c["onto"] = []
        c["pool"] = damage_pool(s, defenders)
        ask_assignment(g)
        return
    _deal(g)


def refuse_illegal(s, attackers, defenders, assignment):
    """465.2.c.6: a player must obey every restriction on assignment if able."""
    bad = validate_assignment(s, attackers, defenders, assignment)
    if bad:
        raise RulesError("that damage assignment is not legal: %s" % "; ".join(bad))


def _deal(g):
    """465.2.d: deal the damage both sides assigned, simultaneously."""
    s = g.s
    c = s.choosing
    index = c["bf"]
    attackers = attacking_units(s, index)
    defenders = defending_units(s, index)
    onto_defenders = list(c["first"] or [])
    onto_attackers = list(c["onto"])
    refuse_illegal(s, defenders, attackers, dict(onto_attackers))
    s.choosing = None

    for oid, amount in onto_defenders + onto_attackers:
        unit = s.unit(oid)
        unit["dmg"] += amount
        g.note("  %s [%s] takes %d damage (%d/%d)"
               % (unit["name"], oid, amount, unit["dmg"], s.might_of(unit)),
               seat=unit["ctrl"])
    # 465.3: skip the FEPR process and cancel any outstanding Tasks; proceed to
    # the Resolution Step. Killing the dead is 323.5, and happens in the Combat
    # Cleanup that opens that step.
    cancel_outstanding(g)


def cancel_outstanding(g):
    """465.3: cancel every outstanding Task that is not the rest of Combat.

    The Combat Cleanup at 466.1 is next whatever else was queued, so anything
    the Combat Showdown Step left outstanding is dropped here rather than run
    between the damage and the cleanup that heals and recalls. A Cleanup dropped
    this way is not lost: 466.7 ends combat with a status change, which makes
    one outstanding again.
    """
    s = g.s
    keep, dropped = [], []
    for task in s.tasks:
        (keep if task[0] in COMBAT_TASKS or task == ("cleanup", "combat")
         else dropped).append(task)
    if dropped:
        s.tasks = keep
        g.note("  the Damage Step skips the FEPR process and cancels %d outstanding "
               "task(s) (465.3)" % len(dropped))
    return dropped


# -- Step 3: the Resolution Step (466) -----------------------------------

def fepr_window(g, index):
    """466.2 / 466.4 / 466.6: resolve what the step just finished put on the Chain.

    Each of the three is written in the rules as a Task whose whole content is
    "resolve any items on the chain ... and associated FEPR before performing
    this step". So it is a Task here too, and it re-queues itself until the
    Chain is empty — which in a vanilla game is immediately, and in a game with
    card text is the window a Reaction is played in.
    """
    s = g.s
    if not s.chain:
        return
    s.tasks.insert(0, ("combat_fepr", index))
    chain.fepr_step(g)


def result_step(g, index):
    """466.3: determine the Combat Result."""
    s = g.s
    bf = s.battlefield(index)
    location = loc_bf(index)

    # 466.1's Combat Special Cleanup ran as the Task queued before this one —
    # it is the one that healed every unit (3c) and recalled the Attackers if
    # any Defender survived (3d), and it sets `combat_recalled` so this step can
    # tell a repel from a rout.
    remaining = s.units_at(location)
    seats = set(u["ctrl"] for u in remaining)

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


def control_step(g, index):
    """466.5: with nothing staged here, the side left standing takes the
    battlefield, and that is a Conquer (466.5.d)."""
    s = g.s
    bf = s.battlefield(index)
    location = loc_bf(index)
    remaining = s.units_at(location)
    seats = set(u["ctrl"] for u in remaining)

    if bf["sd_staged"] or bf["cb_staged"]:
        return
    # This runs whether or not the attackers were repelled: a defender who has
    # just held off an attack, and who may not have controlled the battlefield
    # before it, takes it. 466.5.e says so in as many words.
    if len(seats) == 1:
        winner = next(iter(seats))
        if bf["ctrl"] != winner:
            scoring.establish_control(g, winner, index)
    bf["contested"] = False                                # 466.5.a
    bf["contested_by"] = None
    if not remaining and bf["ctrl"] is not None:
        g.note("%s becomes uncontrolled (466.5.b)" % bf["name"])
        bf["ctrl"] = None


def end_step(g, index):
    """466.7: Combat ends, and the designations go with it."""
    s = g.s
    bf = s.battlefield(index)
    g.note("combat at %s ends; the Attacker and Defender designations are removed "
           "(466.7, 466.7.a)" % bf["name"])
    strip_designations(g)                                  # 466.7.a
    s.showdown = None
    # 313.5: the turn is back in a Neutral State, so nobody holds Focus, and the
    # Priority that came with it goes too.
    s.priority = None
    s.combat_recalled = False
    g.status_changed()
