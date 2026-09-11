"""The turn (300-324): its states, its phases, the mandatory steps, the cleanups.

Two things here decide whether the rest of the kernel can be trusted.

**Everything that loops over both players loops in Turn Order** (303.2.a), never
over `range(2)`. Setup draws, mulligans, pool emptying — all of them. A loop over
seat numbers bakes the labels into the order of events, and the perfect-symmetry
test then fails for a reason that has nothing to do with the rule being tested.
It is also just what 303.2.a says.

**The Cleanup is a real procedure, not a tidy-up.** Rule 323 lists ten numbered
tasks in an order, 322 repeats the whole thing until the state settles, and 324
lets a caller insert extra steps at named positions. Most of the game's state
changes — who controls what, what is contested, when a Showdown opens, when a
Combat opens — happen here and nowhere else, so the numbering is preserved in the
code and each step carries its rule id.
"""
import cards

from . import abilities, actions, layers, scoring
from .state import (AWAKEN, BASE, BEGINNING, CHANNEL, DRAW, ENDING, MAIN,
                    RulesError, loc_base, loc_bf, new_battlefield)

#: 322 repeats a Cleanup until nothing changes. A rule that fights itself would
#: spin forever, so the loop is bounded and a breach is a loud failure rather
#: than a hang. 64 is far above anything the rules can produce (the whole of 323
#: touches two battlefields and a handful of units).
MAX_CLEANUPS = 64


# -- setup (110-118) -----------------------------------------------------

def setup(g):
    """The setup process, up to but not including mulligans (110-116)."""
    s = g.s
    for seat in s.turn_order(s.first_player):
        # 114: Main and Rune decks shuffled SEPARATELY, each on this seat's own
        # stream so the order does not depend on what the opponent brought.
        s.main_deck[seat] = list(g.decks[seat].main_cards())
        s.rune_deck[seat] = list(g.decks[seat].rune_cards())
        s.seat_rng[seat] = g.shuffle(seat, s.main_deck[seat])
        s.seat_rng[seat] = g.shuffle(seat, s.rune_deck[seat])
        # 112: the Chosen Champion is set aside into the Champion Zone, not
        # shuffled in. It is a Main Deck Card (133.4) and is played from there.
        s.champion[seat] = ([g.decks[seat].chosen_champion]
                            if g.decks[seat].chosen_champion else [])

    # 485.5: each player randomly selects one of their three battlefields.
    #
    # They are placed into the Battlefield Zone in TURN ORDER — the first
    # player's at index 0. The rule places them "simultaneously" and says
    # nothing about order, so the order is the engine's to choose, and choosing
    # turn order is what makes battlefield indices survive a mirror: swap who
    # goes first and index 0 is still the first player's battlefield. Indexing
    # by seat number instead makes every loop over battlefields asymmetric.
    for seat in s.turn_order(s.first_player):
        provided = g.decks[seat].battlefield_cards()
        if not provided:
            raise RulesError("seat %d provided no battlefields (103.4)" % seat)
        s.seat_rng[seat], pick = g.choose(seat, provided)
        s.battlefields.append(new_battlefield(len(s.battlefields), pick, seat))

    # 116: players each draw 4, in turn order.
    for seat in s.turn_order(s.first_player):
        actions.draw(g, seat, g.mode["opening_hand"], reason="opening hand")

    g.note("setup: seat %d goes first; battlefields %s"
           % (s.first_player, " and ".join(b["name"] for b in s.battlefields)))
    g.note("victory score is %d (485.3)" % s.victory_target)

    # 117: in turn order, players perform their Mulligan. 118: then the first
    # player takes their turn.
    s.tasks.extend([("mulligan", seat) for seat in s.turn_order(s.first_player)])
    s.tasks.append(("begin_game", None))


# -- phases (314-317) ----------------------------------------------------

def enter_phase(g, phase):
    """Begin a phase and make its mandatory Tasks outstanding."""
    s = g.s
    s.phase = phase
    seat = s.turn_player
    queued = []

    if phase == AWAKEN:
        queued = [("awaken", None)]
    elif phase == BEGINNING:
        # 315.2.a Beginning Step, then 315.2.b Scoring Step. The Beginning Step
        # is where 383.1's "at" conditions sit — "at the beginning of your turn"
        # is a Triggered Ability, so the step raises the event and the Scoring
        # Step follows it.
        queued = [("beginning_step", None), ("hold", None)]
    elif phase == CHANNEL:
        queued = [("channel", None)]
    elif phase == DRAW:
        queued = [("draw", None)]
    elif phase == MAIN:
        # 316.2: these Tasks become outstanding IN THE SPECIFIED ORDER.
        queued = [("empty_pools", None)]
    elif phase == ENDING:
        # 317.1 Ending Step, then 317.2 Expiration Step, which invokes an Ending
        # Special Cleanup with three inserted steps.
        queued = [("cleanup", "ending")]

    # 319.2: a Cleanup becomes an Outstanding Task after the game transitions
    # between phases. It goes after the phase's own Tasks: the transition is
    # what triggers it, and a Cleanup before anything has happened has nothing
    # to settle.
    queued.append(("cleanup", ""))
    s.tasks[0:0] = queued
    if phase != MAIN:
        g.note("— turn %d, seat %d — %s phase" % (s.turn, seat, phase))


def begin_turn(g):
    """Start a turn at the Awaken Phase (315.1)."""
    s = g.s
    s.turn += 1
    if s.turn > g.MAX_TURNS:
        # Every game must end by a rule — 472's Victory Score, or the point
        # 431.2.c hands over on each burn out until someone passes it. A game
        # that runs past this bound has found a way not to, and that is a
        # finding, not a timeout.
        raise RulesError("turn %d: this game is not ending by any rule (472, 431.3)"
                         % s.turn)
    for bf in s.battlefields:
        # 470 is per turn: the record of who has scored what resets here.
        bf["scored"] = []
    # 371.1 and 383.3.e.1 both count "each turn", and 812.1.c asks what you have
    # played "on the same turn". Both records start the turn empty.
    s.used = dict((k, v) for k, v in s.used.items() if not k.endswith("|turn"))
    s.played = [[], []]
    # 812.1.c again, in the other direction: emptying that record closes every
    # Legion gate, and 727.1.b makes the Dependent Ability Inactive the moment
    # the Condition stops holding — not at the first Cleanup of the new turn.
    layers.recompute(g)
    enter_phase(g, AWAKEN)


def pass_turn(g):
    """317.3: the next player with their turn queued becomes the Turn Player."""
    s = g.s
    s.turn_player = 1 - s.turn_player
    g.note("turn passes to seat %d (317.3)" % s.turn_player)
    begin_turn(g)


def next_phase(g):
    """335: with nothing outstanding, proceed to the next phase of the turn."""
    s = g.s
    order = {AWAKEN: BEGINNING, BEGINNING: CHANNEL, CHANNEL: DRAW, DRAW: MAIN}
    if s.phase in order:
        enter_phase(g, order[s.phase])
    elif s.phase == ENDING:
        pass_turn(g)
    else:
        raise RulesError("nothing to advance from the %s phase" % s.phase)


# -- the mandatory Tasks -------------------------------------------------

def run_task(g, name, arg):
    s = g.s
    seat = s.turn_player
    if name == "cleanup":
        run_cleanup(g, arg or "")
    elif name == "mulligan":
        s.choosing = {"what": "mulligan", "seat": arg, "aside": []}
        ask_mulligan(g)
    elif name == "begin_game":
        # 118: begin play with the First Player taking their turn.
        begin_turn(g)
    elif name == "beginning_step":
        # 315.2.a / 383.1: the point in the turn sequence an "at the beginning
        # of" ability names. `who` on the trigger is what tells a "your turn"
        # ability from an "each turn" one; the event carries the Turn Player.
        abilities.emit(g, "beginning_phase", seat=seat, turn=s.turn)
    elif name == "awaken":
        # 315.1.b: the Turn Player readies all Game Objects they control.
        readied = [o for o in (s.units + s.runes) if o["ctrl"] == seat and o["exh"]]
        for obj in readied:
            obj["exh"] = False
        g.note("awaken: seat %d readies %d object(s) (315.1.b)" % (seat, len(readied)),
               seat=seat)
        if readied:
            g.status_changed()
    elif name == "triggers":
        # 383.3: abilities that have triggered go onto the Chain. An Outstanding
        # Task and not a step of FEPR, because 334.2.a is exactly this: a Task
        # incurred partway through a process pauses it, and a trigger raised
        # while the Chain is resolving has to reach the Chain before the next
        # FEPR step reads it.
        abilities.put_triggers_on_chain(g)
    elif name == "hold":
        # 315.2.b.2: the Turn Player Holds all Battlefields they Control.
        scoring.hold_all(g, seat)
    elif name == "channel":
        # 315.3.b: 2 runes, plus one for the player going second on their first
        # Channel Phase of the game (485.7).
        n = g.mode["channel_per_turn"]
        if seat != s.first_player and not s.second_channel_used:
            n += 1
            s.second_channel_used = True
            g.note("the player going second channels an extra rune this turn (485.7)",
                   seat=seat)
        actions.channel(g, seat, n)
    elif name == "draw":
        actions.draw(g, seat, 1, reason="draw phase")
    elif name == "empty_pools":
        # 316.3: each player's Rune Pool empties, in turn order.
        for who in s.turn_order():
            actions.empty_pool(g, who)
    elif name == "combat_damage":
        from . import combat
        combat.damage_step(g, arg)                        # 465
    elif name == "combat_fepr":
        from . import combat
        combat.fepr_window(g, arg)                        # 466.2, 466.4, 466.6
    elif name == "combat_result":
        from . import combat
        combat.result_step(g, arg)                        # 466.3
    elif name == "combat_control":
        from . import combat
        combat.control_step(g, arg)                       # 466.5
    elif name == "combat_end":
        from . import combat
        combat.end_step(g, arg)                           # 466.7
    else:
        raise RulesError("no such task %r" % (name,))


def ask_mulligan(g):
    """117: set aside up to two, draw that many, THEN recycle the ones set aside.

    Asked one card at a time, which is the grouping rule of the decision API at
    work: "set aside up to 2 of these 4" is 11 combinations enumerated as a
    product, or 5 options asked at most three times.
    """
    from .decisions import Option
    s = g.s
    seat = s.choosing["seat"]
    aside = list(s.choosing["aside"])
    remaining = list(s.hand[seat])
    for name in aside:
        remaining.remove(name)
    options = [Option(("keep",), "keep this hand (%d set aside)" % len(aside))]
    if len(aside) < g.MULLIGAN_MAX:
        for name in sorted(set(remaining)):
            options.append(Option(("aside", name), "set aside %s" % name))
    g.ask(seat, "mulligan", options,
          prompt="seat %d's mulligan — set aside up to %d (117.1)"
                 % (seat, g.MULLIGAN_MAX))


def finish_mulligan(g, seat, aside):
    """117.1 set aside, 117.2 draw as many, 117.3 THEN recycle.

    The order matters and is easy to get backwards: shuffling the set-aside
    cards back before redrawing lets a card you have just thrown away come
    straight back, which is not the mulligan the rules describe.
    """
    s = g.s
    if len(aside) > g.MULLIGAN_MAX:
        raise RulesError("a mulligan sets aside at most %d cards (117.1)" % g.MULLIGAN_MAX)
    if not aside:
        g.note("seat %d keeps their hand" % seat, seat=seat)
        return
    for name in aside:
        s.hand[seat].remove(name)
    actions.draw(g, seat, len(aside), reason="mulligan")
    s.main_deck[seat].extend(aside)
    # 431.2.b / 416: cards recycled together are randomised.
    s.seat_rng[seat] = g.shuffle(seat, s.main_deck[seat])
    g.note("seat %d mulligans %d, keeping %d"
           % (seat, len(aside), len(s.hand[seat]) - len(aside)), seat=seat)


# -- cleanups (318-324) --------------------------------------------------

def run_cleanup(g, special=""):
    """322: repeat the Cleanup until one occurs with no change in the state.

    324.2: if events during a Special Cleanup require another Cleanup, a NORMAL
    Cleanup is invoked, not another iteration of the special one — so the
    inserted steps run on the first pass only.
    """
    s = g.s
    for i in range(MAX_CLEANUPS):
        changed = cleanup_once(g, special if i == 0 else "")
        if s.pending is not None:
            # 323.12/323.13 need the Turn Player to choose which Battlefield
            # opens. The answer re-queues a Cleanup, which is 322 anyway.
            return
        if not changed or s.winner is not None:
            return
    raise RulesError("a cleanup changed the state %d times in a row without settling "
                     "(322)" % MAX_CLEANUPS)


def cleanup_once(g, special=""):
    """One Cleanup, in the order rule 323 lists its tasks. True if it changed anything."""
    s = g.s
    changed = False

    # 473-480 before anything reads a trait. 319 makes a Cleanup outstanding
    # after every state change, so recomputing here is what makes a continuous
    # effect continuous: 323.5's lethal check two lines below compares damage
    # against a Might that the layers have already produced.
    layers.recompute(g)

    # 323.1 (1). The victory check.
    actions.check_victory(g, "323.1")
    if s.winner is not None:
        return False

    # 323.2 (2). Assign or remove the Attacker/Defender designation from Units.
    # This is what 464.2.c.3.a defers to: a unit that becomes present after
    # combat opened is designated HERE, in the cleanup that follows the action
    # which brought it, and a unit that leaves loses the designation the same
    # way (323.2.c).
    from . import combat as _combat
    if _combat.apply_designations(g):
        changed = True

    # 323.5 (3b). Every unit with lethal damage marked on it is killed. Nothing
    # else does this, so a unit damaged outside combat would sit there until
    # something healed it.
    for unit in list(s.units):
        if unit["unit"] and unit["dmg"] > 0 and unit["dmg"] >= s.might_of(unit):
            actions.to_trash(g, unit["id"], reason="lethal damage marked (323.5)")
            changed = True

    if special == "combat":
        changed = _combat_inserts(g) or changed
    elif special == "ending":
        changed = _ending_inserts(g) or changed

    # 323.6 (4). Players lose control of battlefields their units have left, if
    # the turn is in an Open State and no Showdown or Combat is ongoing there.
    for bf in s.battlefields:
        if bf["ctrl"] is None or s.is_closed():
            continue
        if s.showdown is not None and s.showdown["bf"] == bf["i"]:
            continue
        if not s.units_at(loc_bf(bf["i"]), bf["ctrl"]):
            g.note("seat %d loses control of %s (323.6)" % (bf["ctrl"], bf["name"]),
                   seat=bf["ctrl"])
            bf["ctrl"] = None
            changed = True

    # 323.7 (5). Anything resting where it does not belong goes home: any
    # permanent in a base that is not its controller's, and unattached non-Unit
    # Gear at a battlefield. Without this a unit that walked into the opponent's
    # base stays there for the rest of the game, reading on the board as a
    # presence it never has.
    for unit in list(s.units):
        where, _, _idx = unit["loc"].partition(":")
        if where == BASE and unit["loc"] != loc_base(unit["ctrl"]):
            g.note("%s [%s] is in another player's base (323.7)"
                   % (unit["name"], unit["id"]), seat=unit["ctrl"])
            actions.recall(g, unit["id"])
            changed = True
        elif where != BASE and not unit["unit"]:
            g.note("%s [%s] is unattached Gear at a battlefield (323.7)"
                   % (unit["name"], unit["id"]), seat=unit["ctrl"])
            actions.recall(g, unit["id"])
            changed = True

    # 323.8 (6) and 323.9 (7)/323.10 (7a). What is Staged where. Recomputed from
    # the board rather than latched, because 323.8.a and 323.9.a both say the
    # staging REMAINS only while its condition holds.
    for bf in s.battlefields:
        seats_here = set(u["ctrl"] for u in s.units_at(loc_bf(bf["i"])))
        was = (bf["sd_staged"], bf["cb_staged"])
        bf["sd_staged"] = bool(bf["contested"] and bf["contested_by"] in seats_here)
        bf["cb_staged"] = bool(bf["contested"] and len(seats_here) == 2)
        if (bf["sd_staged"], bf["cb_staged"]) != was:
            changed = True

    # 323.11 (8). Remove Contested from a battlefield with no units controlled by
    # the player who applied it and no Showdown or Combat ongoing there.
    for bf in s.battlefields:
        if not bf["contested"]:
            continue
        ongoing = s.showdown is not None and s.showdown["bf"] == bf["i"]
        if ongoing or s.units_at(loc_bf(bf["i"]), bf["contested_by"]):
            continue
        g.note("%s stops being contested (323.11)" % bf["name"])
        bf["contested"] = False
        bf["contested_by"] = None
        bf["sd_staged"] = False
        bf["cb_staged"] = False
        changed = True
        # 323.11.a: if that leaves units at an uncontested battlefield their
        # controller does not control, their controller applies Contested.
        for seat in s.turn_order():
            if seat != bf["ctrl"] and s.units_at(loc_bf(bf["i"]), seat):
                bf["contested"] = True
                bf["contested_by"] = seat
                g.note("%s becomes CONTESTED by seat %d (323.11.a)" % (bf["name"], seat),
                       seat=seat)
                break

    # 323.12 (9) and 323.13 (10). A Showdown or a Combat opens, at a battlefield
    # the Turn Player chooses, and only from a Neutral Open State.
    #
    # NINE BEFORE TEN, and the numbering is doing real work. Both steps require a
    # Neutral Open State, and opening either one leaves it — so with a Showdown
    # staged at one battlefield and a Combat at another, 323.12 takes the
    # Showdown and 323.13 does not run at all this cleanup. Taking the Combat
    # first (which reads as the more urgent thing, and is what this engine did)
    # opens the wrong fight and leaves the other staged for a later cleanup.
    #
    # 323.12's own "without a Combat staged" is what keeps the two disjoint: a
    # battlefield with both staged belongs to 323.13, and 461.3/464.1 open it as
    # a Combat Showdown.
    if not s.is_closed() and not s.is_showdown():
        showdowns = [b["i"] for b in s.battlefields
                     if b["sd_staged"] and not b["cb_staged"]]
        combats = [b["i"] for b in s.battlefields if b["cb_staged"]]
        if showdowns:
            _open_at(g, showdowns, combat=False)
            return True
        if combats:
            _open_at(g, combats, combat=True)
            return True

    # 323.14 (10a). A Combat staged where a Non-Combat Showdown is ongoing turns
    # that Showdown into a Combat Showdown.
    if s.showdown is not None and not s.showdown["combat"]:
        bf = s.battlefield(s.showdown["bf"])
        if bf["cb_staged"]:
            s.showdown["combat"] = True
            g.note("the Showdown at %s becomes a Combat Showdown (323.14)" % bf["name"])
            # 464.2.c runs for this way in too (464.1's second opening). The one
            # difference is Focus: 464.2.c.1.b leaves it with whoever already
            # has it, so nothing here touches `focus`.
            _combat.designate(g, bf["i"])
            changed = True

    return changed


def _combat_inserts(g):
    """466.1.a: "3c. Heal all Units" and "3d. Recall Attackers ... if Defenders
    are still present"."""
    from . import combat
    s = g.s
    changed = False
    for unit in s.units:                                   # 3c
        if unit["unit"] and unit["dmg"]:
            unit["dmg"] = 0
            changed = True
    index = s.showdown["bf"]
    bf = s.battlefield(index)
    # 466.1.a.2 recalls ATTACKERS, which is the designation and not the side of
    # the table: a unit that arrived mid-combat is an attacker because 323.2.a
    # made it one two steps ago, in this same cleanup.
    attackers = combat.attacking_units(s, index)
    defenders = combat.defending_units(s, index)
    if attackers and defenders:                            # 3d
        for unit in attackers:
            actions.recall(g, unit["id"])
        g.note("attackers repelled at %s — recalled (466.1.a.2)" % bf["name"])
        s.combat_recalled = True
        changed = True
    return changed


def _ending_inserts(g):
    """317.2.b-d: "3c. Heal all Units", "3d. all 'this turn' effects expire",
    "3e. Each player's Rune Pool empties"."""
    s = g.s
    changed = False
    healed = [u for u in s.units if u["unit"] and u["dmg"]]
    for unit in healed:                                    # 3c
        unit["dmg"] = 0
    if healed:
        g.note("end of turn: healed %d unit(s) (317.2.b)" % len(healed))
        changed = True
    # 3d: all "this turn" effects expire. Three separate things end here, and
    # each is a rule of its own: a continuous effect with a `this_turn` duration
    # (477), a Delayed Ability whose window was this turn (391), and the Stunned
    # status, which 423.1.a.2 names this exact step for.
    if layers.expire(g, "this_turn"):
        changed = True
    if abilities.retire_delayed(g, "this_turn"):
        changed = True
    stunned = [u for u in s.units if u["stunned"]]
    for unit in stunned:                                   # 423.1.a.2
        unit["stunned"] = False
    if stunned:
        g.note("end of turn: %d unit(s) stop being Stunned (423.1.a.2)" % len(stunned))
        changed = True
    # 383.1: "at the end of this turn" is a point in the turn sequence, and this
    # is it — after the expirations, so an ability that looks at the board sees
    # the board the next turn will start from.
    abilities.emit(g, "end_of_turn", seat=s.turn_player, turn=s.turn)
    for seat in s.turn_order():                            # 3e
        if s.energy[seat] or s.power[seat]:
            actions.empty_pool(g, seat)
            changed = True
    return changed


def _open_at(g, candidates, combat):
    """Open a Showdown or a Combat, asking the Turn Player which if there is a
    choice (323.12, 323.13)."""
    from .decisions import Option
    s = g.s
    if len(candidates) == 1:
        open_showdown(g, candidates[0], combat)
        return
    s.choosing = {"what": "open_showdown", "combat": combat}
    options = [Option(("at", i), "open %s at %s"
                      % ("combat" if combat else "a showdown", s.battlefield(i)["name"]))
               for i in candidates]
    g.ask(s.turn_player, "target", options,
          prompt="the Turn Player chooses where %s opens (%s)"
                 % ("combat" if combat else "a showdown", "323.13" if combat else "323.12"))


def open_showdown(g, index, combat):
    """344/345, and 464.2 when it is a Combat Showdown."""
    s = g.s
    bf = s.battlefield(index)
    # 345: the player who applied Contested gains Focus. 464.2.c.1.a says the
    # same thing for a showdown that opens as part of combat — the Attacker,
    # which is that same player.
    focus = bf["contested_by"]
    if focus is None:
        raise RulesError("%s has nothing that applied Contested, so no one can take "
                         "Focus (345)" % bf["name"])
    s.showdown = {"bf": index, "combat": bool(combat), "focus": focus,
                  "passes": 0, "closed": False}
    if combat:
        g.note("COMBAT opens at %s as a Combat Showdown; seat %d is the Attacker "
               "and takes Focus (464.1, 464.2.c.1, 464.2.d)" % (bf["name"], focus),
               seat=focus)
        # 464.2.c: establish who is Attacker and who is Defender, and designate
        # their units here. Step 2 of 464.2.a, before 464.2.d's Focus, which
        # `focus` above has already taken because 464.2.c.1.a is the same player.
        from . import combat as _combat
        _combat.designate(g, index)
    else:
        g.note("a SHOWDOWN opens at %s; seat %d applied Contested and takes Focus "
               "(344, 345)" % (bf["name"], focus), seat=focus)
    # 319.1: the game transitioned into a Showdown State.
    g.status_changed()


# -- what a card is ------------------------------------------------------

def category(name):
    """The Category of a card (133), as the kernel's four kinds."""
    kind = cards.card_type(name)
    if kind == cards.UNIT:
        return "unit"
    if kind == cards.GEAR:
        return "gear"
    if kind == cards.SPELL:
        return "spell"
    return "other"


def play_locations(s, seat, name):
    """355.2.a: a Unit enters at its controller's Base or a Battlefield they control."""
    if category(name) != "unit":
        # 359.2.d: a non-Unit Gear enters Ready at the player's Base. No choice.
        return [loc_base(seat)]
    spots = [loc_base(seat)]
    for bf in s.battlefields:
        if bf["ctrl"] == seat:
            spots.append(loc_bf(bf["i"]))
    return spots
