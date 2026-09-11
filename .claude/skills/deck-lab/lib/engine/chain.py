"""The Chain and Showdowns (325-348) — HOT FEPR, and the alternating window.

The spec for this module is not prose: it is
`rules-report/lib/hot-fepr-primer.json` and `showdowns-primer.json`, two
documents whose every transition is a verbatim-verified citation of the Core
Rules. Each function below implements one of their steps and carries the rule id
the primer cites for it, and `engine/selftest.py` walks the primers' own `exits`
and asserts this module makes the transition each one names.

The shapes that matter:

* **The Chain is a stack read from the right.** `chain[-1]` is the newest item,
  and 340.1 resolves exactly that one — ONE item, not the whole Chain. A Chain
  of three resolves in three separate passes with a window between each.
* **Finalize is bookkeeping, not a window** (337.1.a). It does not pass Priority,
  and a Unit or Gear never waits to be answered: 337.2 sends it straight to
  Resolve, which is why "respond to a unit" is not a thing you can do.
* **A Showdown is Focus, not Priority** (313). Focus alternates; the window
  closes only when every player has passed once in sequence (347.2.a), and a
  single pass never closes it.
"""
from . import actions, scoring, turn
from .decisions import Option
from .state import RulesError, loc_base, loc_bf


# -- putting something on the Chain (349-359) ----------------------------

def play_card(g, seat, name, from_zone):
    """354: move the card from its zone to the Chain as a Pending Item.

    This Closes the State (354.1), which is what makes the rest of the turn
    behave differently until the Chain empties.
    """
    s = g.s
    zone = getattr(s, from_zone)
    if name not in zone[seat]:
        raise RulesError("%s is not in seat %d's %s" % (name, seat, from_zone))
    zone[seat].remove(name)
    item = {"id": s.mint("c"), "ctrl": seat, "name": name,
            "kind": turn.category(name), "pending": True, "loc": "", "src": from_zone}
    s.chain.append(item)
    # Playing something is what resets the pass sequence (339.1).
    s.passes = 0
    g.note("seat %d plays %s [%s] onto the Chain — pending (354)" % (seat, name, item["id"]),
           seat=seat)
    # 319.3: a Cleanup becomes outstanding after a Pending Item is added.
    g.need_cleanup()
    # 355.2: for a UNIT, choose the Location it will enter. Asked now, while the
    # item is pending, which is where step 2 of the play process sits.
    #
    # Only for a unit: 359.2.d puts a non-Unit Gear at its controller's Base with
    # no choice to make, and a Spell never enters the Board at all. Asking anyway
    # would put a one-option decision in front of every spell in the game and
    # count it in every perft.
    if item["kind"] == "unit":
        spots = turn.play_locations(s, seat, name)
        s.choosing = {"what": "play_location", "item": item["id"]}
        g.ask(seat, "target",
              [Option(("at", loc), "%s enters at %s" % (name, _pretty(s, loc)))
               for loc in spots],
              prompt="where does %s enter? (355.2)" % name)
    elif item["kind"] == "gear":
        item["loc"] = loc_base(seat)
    return item


def _pretty(s, location):
    from .state import where
    return where(s, location)


# -- FEPR (336-340) ------------------------------------------------------

def fepr_step(g):
    """One step of the FEPR process. Returns True if it did something."""
    s = g.s

    # 337.2 took precedence over everything else: the item just finalized is a
    # Unit, Gear, or an Add ability, so it resolves immediately.
    if s.resolve_now:
        s.resolve_now = False
        resolve_newest(g)
        return True

    if any(c["pending"] for c in s.chain):
        finalize_one(g)                                   # 337.1
        return True

    if s.passes >= 2:
        # 339.1: all players have passed in sequence without adding anything.
        s.passes = 0
        resolve_newest(g)
        return True

    # 338: the player with Priority may play something legally timed, or pass.
    if s.priority is None:
        s.priority = s.chain[-1]["ctrl"]
    _ask_execute(g, s.priority)
    return True


def _ask_execute(g, seat):
    options = [Option((k,), label) for k, label in chain_plays(g, seat)]
    options.append(Option(("pass",), "pass priority (338.1.b)"))
    g.s.choosing = None
    g.ask(seat, "chain", options, window="chain",
          prompt="seat %d has priority in a Closed State (338.1)" % seat)


def chain_plays(g, seat):
    """What `seat` may legally play into a Closed State (338.1.a).

    Empty, always, in the vanilla slice: 338.1.a.1 says cards and activated
    abilities cannot by default be played during a Closed State, and 338.1.a.2
    says what qualifies is something with Reaction — which is card text, and
    this slice executes none. The generator exists so that the window is a real
    window with a real (currently empty) option set, rather than a hole where
    one will have to be cut later.
    """
    return []


def finalize_one(g):
    """337.1: the controller of the OLDEST pending item completes playing it.

    337.1.b makes the order the order they were appended, and 337.1.a says
    finalizing does not pass Priority — so no window opens here, however many
    items are waiting.
    """
    s = g.s
    item = next(c for c in s.chain if c["pending"])
    seat = item["ctrl"]

    # 356/357: determine and pay the cost. 358: check legality. A cost that
    # cannot be paid now would mean the option list was generated against a
    # different board, which is a kernel bug rather than a legal outcome.
    actions.pay(g, seat, item["name"])
    if item["kind"] == "unit" and item["loc"] not in turn.play_locations(s, seat, item["name"]):
        raise RulesError("%s would enter at %s, which is no longer a valid location "
                         "(358.1)" % (item["name"], item["loc"]))

    item["pending"] = False                               # 359.1
    g.note("  %s [%s] is finalized (359)" % (item["name"], item["id"]), seat=seat)
    # 319.4: a Cleanup becomes outstanding after a Pending Item is finalized.
    g.need_cleanup()

    if item["kind"] in ("unit", "gear"):
        # 337.2: a Unit or Gear resolves immediately — it never waits on the
        # Chain to be answered.
        s.resolve_now = True
        return

    if any(c["pending"] for c in s.chain):
        return                                            # 337.3
    # 337.4: the controller of the next item on the chain gains Priority.
    s.priority = s.chain[-1]["ctrl"]
    s.passes = 0


def resolve_newest(g):
    """340.1: the newest Finalized Chain Item resolves, in its entirety."""
    s = g.s
    index = None
    for i in range(len(s.chain) - 1, -1, -1):
        if not s.chain[i]["pending"]:
            index = i
            break
    if index is None:
        raise RulesError("nothing on the Chain is finalized, so nothing can resolve (340.1)")
    item = s.chain.pop(index)
    seat = item["ctrl"]

    if item["kind"] == "unit":
        # 359.2.c: a Unit enters the Board EXHAUSTED at the Location chosen.
        actions.put_into_play(g, seat, item["name"], item["loc"], True, "chain")
    elif item["kind"] == "gear":
        # 359.2.d: a non-Unit Gear enters the Board Ready at the player's Base.
        actions.put_into_play(g, seat, item["name"], item["loc"], False, "chain")
    else:
        # 351.2: a Spell's game effects are executed and the card is then placed
        # in the trash. This slice executes no card text, so the effect is
        # nothing and the log says as much — an unexecuted spell that looked
        # executed would be the worst possible silent failure.
        s.trash[seat].append(item["name"])
        g.note("  %s [%s] resolves — vanilla kernel, its text is not executed (340.1)"
               % (item["name"], item["id"]), seat=seat)

    # 319.5: a Cleanup becomes outstanding after an item leaves the Chain.
    g.need_cleanup()

    if not s.chain:
        s.priority = None                                 # 340.2: an Open State
        s.passes = 0
        return
    if any(c["pending"] for c in s.chain):
        return                                            # 340.3
    # 340.4: the controller of the newest item on the chain gains Priority.
    s.priority = s.chain[-1]["ctrl"]
    s.passes = 0


def pass_priority(g, seat):
    """338.1.b.1 and 339: pass, then ask whether the window has closed."""
    s = g.s
    s.passes += 1
    s.priority = 1 - seat
    g.note("  seat %d passes priority (338.1.b)" % seat, seat=seat)
    # 339.1 is checked by `fepr_step`, which is Step 3 asking its one question:
    # has everyone passed in sequence with nothing added?


# -- Showdowns (341-348) -------------------------------------------------

def showdown_step(g):
    """347: the player with Focus plays something legally timed, or passes."""
    s = g.s
    sd = s.showdown
    seat = sd["focus"]
    # 313.2: a player who gains Focus also gains Priority.
    s.priority = seat
    options = [Option((k,), label) for k, label in showdown_plays(g, seat)]
    options.append(Option(("pass",), "pass focus (347.2)"))
    s.choosing = None
    g.ask(seat, "chain", options, window="showdown",
          prompt="seat %d has Focus in the Showdown at %s (347)"
                 % (seat, s.battlefield(sd["bf"])["name"]))


def showdown_plays(g, seat):
    """What `seat` may play with Focus (347.1).

    Empty in the vanilla slice for the same reason as `chain_plays`: 343.1.a and
    343.1.b close a Showdown State to cards and abilities by default, and what
    opens it is a keyword this slice does not read.
    """
    return []


def pass_focus(g, seat):
    """347.2: pass. A full sequence of passes ends the Showdown (347.2.a)."""
    s = g.s
    sd = s.showdown
    sd["passes"] += 1
    g.note("  seat %d passes focus (347.2)" % seat, seat=seat)
    if sd["passes"] >= 2:
        close_showdown(g)
    else:
        sd["focus"] = 1 - seat                            # 347.2.b
        g.note("  focus passes to seat %d (347.2.b)" % sd["focus"], seat=sd["focus"])


def close_showdown(g):
    """348: everyone passed, so the Showdown closes."""
    s = g.s
    sd = s.showdown
    bf = s.battlefield(sd["bf"])
    g.note("the Showdown at %s closes (348)" % bf["name"])
    if sd["combat"]:
        # 348.1: proceed with the remaining steps of Combat. The Showdown stays
        # in place, marked closed, so the turn is still in a Showdown State
        # until combat ends at 466.7.
        sd["closed"] = True
        # The rest of Combat, as the rules number it: the Damage Step (465), the
        # Combat Cleanup that opens the Resolution Step (466.1), and then 466.3,
        # 466.5 and 466.7 as three separate Tasks with the window of 466.2 /
        # 466.4 / 466.6 between each. One Task for all three would run them with
        # the Chain still holding whatever the previous one put there.
        index = sd["bf"]
        s.tasks[0:0] = [("combat_damage", index),
                        ("cleanup", "combat"),
                        ("combat_fepr", index),            # 466.2
                        ("combat_result", index),          # 466.3
                        ("combat_fepr", index),            # 466.4
                        ("combat_control", index),         # 466.5
                        ("combat_fepr", index),            # 466.6
                        ("combat_end", index)]             # 466.7
        return
    # 348.2: a Non-Combat Showdown settles Control.
    seats = set(u["ctrl"] for u in s.units_at(loc_bf(sd["bf"])))
    s.showdown = None
    # 313.5 / 312.2.b: Focus only exists in a Showdown State, and the Priority
    # that came with it goes with it. Left behind, the same position hashes two
    # ways depending on which Showdown last closed there, which is exactly the
    # kind of phantom difference a transposition table would trip over.
    s.priority = None
    if len(seats) == 1:
        seat = next(iter(seats))
        if bf["ctrl"] != seat:
            # 348.2.a.1: this is a Conquer if that player has not yet scored
            # this battlefield this turn.
            scoring.establish_control(g, seat, sd["bf"])
    g.status_changed()
