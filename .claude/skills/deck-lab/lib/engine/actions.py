"""Game Actions (407-444) and Movement (445-458) — the physical operations.

Everything here is something that happens to cards and objects: a draw, a
channel, a move, a recall, a payment. Nothing here decides anything; the
decision-request API does that, and these are what an answer turns into.

The log this writes is deliberately the same auditable record the table writes
(ADR 0007's first half, which ADR 0009 keeps): draws are recorded privately per
seat because 108.7.c makes a hand Private Information, and every other line
names the seat that acted. A game log should read as a sequence of physical
operations, not as a narrative.

Most of this is a port of `table.py`, and where the table learned something the
hard way the comment explaining it is carried across with the code rather than
left behind in the file that no longer runs.
"""
import cards

from .state import (BASE, RulesError, bf_index, is_bf, loc_base, new_rune,
                    new_unit, where)


# -- drawing and running out (413, 431) ---------------------------------

def draw(g, seat, n=1, reason=""):
    """Draw n (413), burning out where the deck runs short (431.1.a)."""
    s = g.s
    drawn = []
    remaining = n
    # A player whose trash is also empty burns out again on the next attempt
    # (431.3), handing a point over each time until someone wins. The bound is
    # the Victory Score, so this always terminates.
    for _ in range(s.victory_target + 2):
        take = min(remaining, len(s.main_deck[seat]))
        for _ in range(take):
            drawn.append(s.main_deck[seat].pop(0))
        remaining -= take
        if remaining <= 0:
            break
        burn_out(g, seat)
        if s.winner is not None:
            break
    s.hand[seat].extend(drawn)
    if drawn:
        # The names are private to the drawing seat. They are still recorded in
        # full so a finished game can be reviewed; `detail` is the part a seat
        # view redacts.
        g.note("seat %d draws %d%s" % (seat, len(drawn), " (%s)" % reason if reason else ""),
               seat=seat, private_to=seat, detail=", ".join(drawn))
    return drawn


def burn_out(g, seat):
    """Run the Burn Out sequence (431.2).

    431.2.c is a point award, and 431.3.a's "burning out repeatedly, giving 1
    point to an opponent each time, until an opponent passes the Victory Score"
    is the only way a game between two empty decks ever ends. Left as a log line
    and nothing else, a decked-out player is immortal.
    """
    s = g.s
    other = 1 - seat
    g.note("seat %d BURNS OUT (431)" % seat, seat=seat)

    # 431.2.b: recycle the trash into the Main Deck, randomised.
    if s.trash[seat]:
        recycled = len(s.trash[seat])
        s.main_deck[seat].extend(s.trash[seat])
        s.trash[seat] = []
        s.seat_rng[seat] = g.shuffle(seat, s.main_deck[seat])
        g.note("  seat %d recycles %d card(s) from trash into their Main Deck (431.2.b)"
               % (seat, recycled), seat=seat)
    else:
        g.note("  seat %d's trash is empty; the Main Deck stays empty (431.3)" % seat,
               seat=seat)

    # 431.2.c: an opponent gains a point. Not a Score — 471.1's restrictions are
    # about Scoring, and this is a plain point gain, so the final-point rule
    # does not apply to it (471.1.a.1).
    gain_point(g, other, "the burn out (431.2.c)")
    # 431.3.c.1: a win from this is immediate, without waiting for a cleanup.
    check_victory(g, "431.3.c.1")
    return s.points[other]


def gain_point(g, seat, reason):
    s = g.s
    s.points[seat] += 1
    g.note("  seat %d gains 1 point from %s -> %d" % (seat, reason, s.points[seat]),
           seat=seat)
    return s.points[seat]


def check_victory(g, rule="472"):
    """472: a player at or past the Victory Score with more points than any
    opponent wins. Checked at every cleanup, and immediately after a burn out."""
    s = g.s
    if s.winner is not None:
        return s.winner
    eligible = [seat for seat in (0, 1) if s.points[seat] >= s.victory_target]
    if not eligible:
        return None
    best = max(eligible, key=lambda seat: s.points[seat])
    if all(s.points[best] > s.points[o] for o in (0, 1) if o != best):
        s.winner = best
        # Both rules, always: 472 is the rule that wins the game and `rule` is
        # the moment it was noticed. A reason naming only the moment reads, in a
        # thousand-game soak, as if the game ended for a different reason each
        # time.
        s.end_reason = "seat %d reached the Victory Score (472, noticed at %s)" % (best, rule)
        g.note("seat %d WINS with %d points (472, at %s)" % (best, s.points[best], rule),
               seat=best)
    return s.winner


# -- runes and the pool (163-168, 429, 430) -----------------------------

def channel(g, seat, n=1, exhausted=False):
    """Channel n runes from the top of the Rune Deck onto the board (430)."""
    s = g.s
    out = []
    for _ in range(n):
        if not s.rune_deck[seat]:
            break  # 430.3: channel as many as possible.
        name = s.rune_deck[seat].pop(0)
        rune = new_rune(s.mint("r"), name, seat, exhausted)
        s.runes.append(rune)
        out.append(rune)
    if out:
        g.note("seat %d channels %d%s: %s"
               % (seat, len(out), " exhausted" if exhausted else "",
                  ", ".join(r["name"] for r in out)), seat=seat)
    elif n:
        g.note("seat %d cannot channel — Rune Deck is empty" % seat, seat=seat)
    return out


def empty_pool(g, seat):
    """Empty a rune pool; unspent Energy and Power are lost (167)."""
    s = g.s
    lost_e, lost_p = s.energy[seat], sum(s.power[seat].values())
    s.energy[seat] = 0
    s.power[seat] = {}
    if lost_e or lost_p:
        g.note("seat %d's rune pool empties (lost %dE, %dP)" % (seat, lost_e, lost_p),
               seat=seat)


def cost_of(name):
    """The printed cost, and whether its Power split is determined.

    The card data carries a Power COUNT and the card's domain list, not one
    domain per symbol. For a single-domain card that is exact; for a two-domain
    card with one Power symbol the printed symbol's domain is not recoverable,
    so the requirement is widened to "any of the card's domains". Permissive
    rather than strict: an engine that refuses a legal play produces games that
    could not happen, which is worse than one that allows a play it should not
    and says so.
    """
    energy = cards.energy_cost(name) or 0
    power = cards.power_cost(name) or 0
    domains = cards.domains(name)
    return {"energy": energy, "power": power, "domains": domains,
            "exact": power == 0 or len(domains) <= 1}


def can_pay(g, seat, name):
    """Is the printed cost payable from the pool plus the runes on the board?"""
    s = g.s
    cost = cost_of(name)
    mine = [r for r in s.runes if r["ctrl"] == seat]
    readied = [r for r in mine if not r["exh"]]
    usable_power = sum(
        n for d, n in s.power[seat].items()
        if not cost["domains"] or d in cost["domains"] or d == "Universal")
    power_short = max(cost["power"] - usable_power, 0)

    # 164.2.b's Power ability costs "Recycle this", not "[E]" — so an EXHAUSTED
    # rune can still be recycled for Power. Requiring a readied one refuses
    # payments the rules allow.
    def matching(runes):
        return [r for r in runes
                if not cost["domains"] or r["domain"] in cost["domains"]]

    spent_runes = matching([r for r in mine if r["exh"]])
    from_exhausted = min(power_short, len(spent_runes))
    from_readied = power_short - from_exhausted
    if from_readied > len(matching(readied)):
        return False, "needs %d Power of %s" % (
            cost["power"], "/".join(cost["domains"]) or "any domain")
    # Only a READIED rune spent on Power costs you Energy; an exhausted one had
    # none left to give.
    capacity = s.energy[seat] + len(readied) - from_readied
    if cost["energy"] > capacity:
        return False, "needs %d Energy, can raise %d" % (cost["energy"], max(capacity, 0))
    return True, ""


def pay(g, seat, name):
    """Pay a card's printed cost, exhausting and recycling runes to do it (357)."""
    s = g.s
    ok, why = can_pay(g, seat, name)
    if not ok:
        raise RulesError("seat %d cannot pay for %s: %s" % (seat, name, why))
    cost = cost_of(name)

    for _ in range(cost["power"]):
        wanted = list(cost["domains"])
        pooled = None
        for d in sorted(s.power[seat]):
            if s.power[seat][d] > 0 and (not wanted or d in wanted or d == "Universal"):
                pooled = d
                break
        if pooled:
            s.power[seat][pooled] -= 1
            if not s.power[seat][pooled]:
                del s.power[seat][pooled]
            continue
        # Spend an already-exhausted rune first: it has no Energy left to give,
        # so recycling it costs the turn nothing else.
        def usable(exhausted):
            return [r for r in s.runes
                    if r["ctrl"] == seat and r["exh"] is exhausted
                    and (not wanted or r["domain"] in wanted)]
        candidates = usable(True) + usable(False)
        if not candidates:
            raise RulesError("seat %d has no rune to produce %s Power"
                             % (seat, "/".join(wanted) or "any"))
        recycle_rune_for_power(g, seat, candidates[0]["id"])
        domain = candidates[0]["domain"] or "Universal"
        s.power[seat][domain] -= 1
        if not s.power[seat][domain]:
            del s.power[seat][domain]

    short = cost["energy"] - s.energy[seat]
    if short > 0:
        tap_for_energy(g, seat, short)
    s.energy[seat] -= cost["energy"]
    g.note("seat %d pays %dE%s for %s%s"
           % (seat, cost["energy"], " + %dP" % cost["power"] if cost["power"] else "",
              name, "" if cost["exact"] else "  [power domain split not in the card data]"),
           seat=seat)


def tap_for_energy(g, seat, count=1):
    """Exhaust readied runes for Energy — [E]: Add [1] (164.2.a, 429)."""
    s = g.s
    available = [r for r in s.runes if r["ctrl"] == seat and not r["exh"]]
    if len(available) < count:
        raise RulesError("seat %d has %d readied rune(s), needs %d"
                         % (seat, len(available), count))
    for rune in available[:count]:
        rune["exh"] = True
    s.energy[seat] += count
    g.note("seat %d exhausts %d rune(s) for %d Energy" % (seat, count, count), seat=seat)


def recycle_rune_for_power(g, seat, oid):
    """Recycle a rune from the board for Power of its domain (164.2.b, 416)."""
    s = g.s
    rune = next((r for r in s.runes if r["id"] == oid), None)
    if rune is None or rune["ctrl"] != seat:
        raise RulesError("rune %r is not controlled by seat %d" % (oid, seat))
    s.runes.remove(rune)
    s.rune_deck[seat].append(rune["name"])
    domain = rune["domain"] or "Universal"
    s.power[seat][domain] = s.power[seat].get(domain, 0) + 1
    g.note("seat %d recycles %s [%s] for 1 %s Power" % (seat, rune["name"], oid, domain),
           seat=seat)


# -- the board (419, 427, 428) ------------------------------------------

def put_into_play(g, seat, name, location, exhausted, from_zone):
    """Put a permanent onto the Board and return it.

    A card has to come from somewhere: accepting one that was in no zone
    conjures a permanent out of nothing and leaves the zone it should have come
    from unchanged, which is a board state no sequence of legal plays reaches.
    """
    s = g.s
    if from_zone == "chain":
        pass  # it was moved to the Chain by 354 and is leaving it now.
    else:
        zone = getattr(s, from_zone, None)
        if zone is None or name not in zone[seat]:
            raise RulesError("%s is not in seat %d's %s" % (name, seat, from_zone))
        zone[seat].remove(name)
    unit = new_unit(s.mint("u"), name, seat, location, exhausted)
    s.units.append(unit)
    g.note("seat %d puts %s [%s] into play %s at %s"
           % (seat, name, unit["id"], "exhausted" if exhausted else "ready",
              where(s, location)), seat=seat)
    if is_bf(location):
        apply_contested(g, unit)
    g.board_changed()
    return unit


def to_trash(g, oid, reason="killed"):
    """Move a permanent from the Board to its owner's trash (428)."""
    s = g.s
    unit = s.unit(oid)
    s.units.remove(unit)
    s.trash[unit["owner"]].append(unit["name"])
    g.note("%s [%s] -> trash (%s)" % (unit["name"], oid, reason), seat=unit["ctrl"])
    g.board_changed()


def banish(g, oid):
    """Banish a permanent (427)."""
    s = g.s
    unit = s.unit(oid)
    s.units.remove(unit)
    s.banished[unit["owner"]].append(unit["name"])
    g.note("%s [%s] is banished" % (unit["name"], oid), seat=unit["ctrl"])
    g.board_changed()


def discard(g, seat, name):
    """Discard from hand to the trash (422)."""
    s = g.s
    if name not in s.hand[seat]:
        raise RulesError("%s is not in seat %d's hand" % (name, seat))
    s.hand[seat].remove(name)
    s.trash[seat].append(name)
    g.note("seat %d discards %s" % (seat, name), seat=seat)


def exhaust(g, oid):
    """414."""
    obj = _object(g.s, oid)
    if obj["exh"]:
        raise RulesError("%s [%s] is already exhausted" % (obj["name"], oid))
    obj["exh"] = True
    g.note("%s [%s] exhausts" % (obj["name"], oid), seat=obj["ctrl"])


def ready(g, oid):
    """415."""
    obj = _object(g.s, oid)
    obj["exh"] = False
    g.note("%s [%s] readies" % (obj["name"], oid), seat=obj["ctrl"])


def _object(s, oid):
    for obj in s.units:
        if obj["id"] == oid:
            return obj
    for obj in s.runes:
        if obj["id"] == oid:
            return obj
    raise RulesError("no object with id %r on the board" % (oid,))


# -- movement (445-458) -------------------------------------------------

def move(g, oid, destination):
    """Move a permanent (420, 446). The Standard Move's cost is not charged here.

    144.2 makes exhausting the unit the cost of a Standard Move, but a spell or
    ability can move a unit without it — so the caller says which happened by
    exhausting or not.
    """
    s = g.s
    unit = s.unit(oid)
    _require_location(s, destination)
    origin = unit["loc"]
    if origin == destination:
        raise RulesError("%s is already at %s" % (unit["name"], where(s, destination)))
    unit["loc"] = destination
    g.note("%s [%s] moves %s -> %s"
           % (unit["name"], oid, where(s, origin), where(s, destination)),
           seat=unit["ctrl"])
    if is_bf(destination):
        # 450: the Destination becomes Contested if it is an uncontested
        # Battlefield the mover does not control.
        apply_contested(g, unit)
    # 453: when a Move action is complete, perform a Cleanup.
    g.need_cleanup()
    return unit


def standard_move_legal(s, unit, destination):
    """Is this Standard Move one the rules allow (144)?

    Returns a reason string when it is not, so the refusals can be told apart —
    a guard that prints the same text as the guard behind it cannot be pinned
    separately from it.
    """
    if not unit["unit"]:
        return "only units have a Standard Move (144)"
    if s.phase != "main":
        return "a Standard Move happens during the Main Phase (144.1.a)"
    if s.is_closed():
        return "a Standard Move cannot be performed during a Closed State (144.1.b)"
    if s.is_showdown():
        return "a Standard Move cannot be performed during a Showdown or Combat (144.1.c)"
    if unit["exh"]:
        return "%s is exhausted and cannot pay its move cost (144.2)" % unit["name"]
    # 446.3.b: a permanent is at its Origin or its Destination and nowhere in
    # between, so "move it to where it is" is not a Move at all. Checked here,
    # first, and phrased differently from `move`'s own refusal: the two are a
    # masking pair, and a pair that prints the same string cannot be pinned
    # apart. Without this one, breaking either shape rule below leaks the unit's
    # own location into the option list and the game dies on `move` instead of
    # failing a check that names the rule.
    if destination == unit["loc"]:
        return "%s is already at %s, which is not a Move (446.3.b)" % (
            unit["name"], destination)

    # 144.4 lists exactly two legal shapes: base -> battlefield (144.4.a) and
    # battlefield -> base (144.4.b). Each refusal below says something different,
    # for the same reason.
    origin_bf = is_bf(unit["loc"])
    dest_bf = is_bf(destination)
    if origin_bf and dest_bf:
        return ("%s would move battlefield -> battlefield, which the Standard Move does "
                "not allow without Ganking (144.4.c)" % unit["name"])
    if not origin_bf and not dest_bf:
        return "a Standard Move goes base -> battlefield or battlefield -> base (144.4)"
    if not dest_bf and destination != loc_base(unit["ctrl"]):
        return "a unit's Standard Move returns to ITS OWN base (144.4.b)"
    return ""


def standard_move(g, oid, destination):
    """A unit's inherent Standard Move: exhaust, then move (144)."""
    s = g.s
    unit = s.unit(oid)
    why = standard_move_legal(s, unit, destination)
    if why:
        raise RulesError(why)
    exhaust(g, oid)
    return move(g, oid, destination)


def recall(g, oid):
    """Return a permanent to its controller's base (454-458). Not a Move."""
    s = g.s
    unit = s.unit(oid)
    unit["loc"] = loc_base(unit["ctrl"])
    # 458.1: damage and statuses survive a Recall.
    g.note("%s [%s] is recalled to base" % (unit["name"], oid), seat=unit["ctrl"])


def deflect_surcharge(obj, seat):
    """809.1.c: the extra Power `seat` pays to choose this object with a spell.

    A hook, not yet a cost: nothing in the vanilla slice targets anything, so no
    play goes through here. It is written because Deflect is a characteristic of
    the OBJECT (809.3) with a rule about WHO pays — "spells and abilities an
    opponent controls" — and getting that half backwards is a cost charged to
    the wrong player, which is the kind of thing that reads as a balance change
    rather than as a bug. 809.1.c.1's "may always be of any Domain" is why this
    returns a bare count and not a domain.
    """
    if seat == obj["ctrl"]:
        return 0
    return obj["deflect"]


def apply_contested(g, unit):
    """190.3.a.1 / 450: a UNIT becoming present contests a battlefield."""
    s = g.s
    # Gear moving to a battlefield does not contest it — 190.3.a says Contested
    # is applied by a Unit.
    if not unit["unit"]:
        return
    bf = s.battlefield(bf_index(unit["loc"]))
    if bf["ctrl"] != unit["ctrl"] and not bf["contested"]:
        bf["contested"] = True
        bf["contested_by"] = unit["ctrl"]
        g.note("%s becomes CONTESTED by seat %d (190.3.a.1)" % (bf["name"], unit["ctrl"]),
               seat=unit["ctrl"])


def _require_location(s, location):
    kind, _, idx = location.partition(":")
    if kind == BASE and idx in ("0", "1"):
        return
    if kind == "bf":
        s.battlefield(idx)
        return
    raise RulesError("%r is not a location — use base:0/base:1 or bf:0/bf:1" % (location,))
