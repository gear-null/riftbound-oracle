"""Abilities (360-406) — passive, activated, triggered, reflexive, delayed, linked.

361.1 lists five structures and the whole of card text is built out of them, so
this module is the shape every card script will be compiled INTO. It executes no
card text of its own: an `Ability` carries Python callables, the tests hand-build
them, and the interpreter (#26) will supply script-driven ones. What is
implemented here is the machinery around those callables — when they are
evaluated, where they function, what they cost, and in what order they happen.

Four things decide whether the rest of this is trustworthy:

* **An ability is data plus a callable, and the STATE holds neither.** A game
  object refers to its abilities by a `(registry key, index)` pair of
  primitives, so `clone()` stays a C-level copy of dicts and a position can
  still be hashed. The registry is card data, shared by every clone, and nothing
  in a game ever writes to it.
* **A gate is evaluated continuously** (727.1.b). `[Legion]`, `[Level N]` and
  `[Empowered]` are the CR's three Dependent Keywords, and the ability they
  introduce is *Inactive* until the condition holds and Inactive again the
  moment it stops. Nothing latches on play: the gate is re-asked every time the
  ability is looked at, which is why a passive whose gate closes mid-turn stops
  applying mid-turn.
* **Presence is a property of the ability, not of the card** (365-366, 384-385).
  A passive that alters costs functions in every zone the card can be played
  from (366.2.a); a triggered ability of a permanent can only evaluate its
  condition on the Board (384.2). The zone list is on the ability.
* **Ordering is never the script's.** Simultaneous triggers go on the Chain in
  the order their controller chooses (383.3.d) and across seats in Turn Order
  starting with the Turn Player (383.3.d.1, 303.2.a). Both are decisions the API
  emits, not a sort the engine picks.

Layers are next door in `layers.py` and replacement effects in
`replacements.py`, because 368.1 makes a Replacement Effect a kind of Passive
Ability and 477 makes a passive's contribution a thing with a layer — two
mechanisms that read this module's objects rather than living inside it.
"""
from .decisions import Option
from .state import RulesError

# -- the vocabulary ------------------------------------------------------

#: 361.1's structures, plus the six replacement kinds, spelled exactly as the
#: card-script DSL spells them (`engine/dsl/schema.py`, `_ABILITIES`) so the
#: interpreter maps a script node onto one of these by name and nothing else.
#:
#: `linked` is NOT here, and 396 is why: "Linked Abilities can contain component
#: Abilities of any type." Being linked is a relation over a SET of abilities on
#: one source, so it is `Ability.link` — a name two abilities share — and not a
#: seventh kind that the other six could not then be.
KINDS = (
    "passive", "activated", "triggered", "reflexive", "delayed",
    "cost_replacement", "enters_modified", "instead", "would", "as_enters",
    "ignoring_cost",
)

#: The trigger events the census counted in the gauntlet, spelled as the DSL's
#: `TRIGGERS` atoms. Four carry a `_trigger` suffix because the bare word is
#: already a game-action primitive in the same vocabulary; the suffix is the
#: DSL's and is kept here so a script's `events` list needs no translation.
#:
#: TWO of the census's rows are deliberately absent, for the same reason and
#: with the DSL's own note as the precedent:
#:
#: * `nth_time` - 383.1.b's "the first time ... each turn" modifies an event
#:   rather than being one. It is reached through `Ability.frequency`.
#: * `delayed_next` - 390.2's "the next time" is a WINDOW on a Delayed Ability,
#:   not a thing that happens. A delayed ability still needs a real event to
#:   wait for, which is why `delay()` takes one AND a window from `WINDOWS`.
#:   The DSL currently spells this as the only event of a delayed ability
#:   (`{"events": ["delayed_next"]}`), and that node cannot say what is being
#:   delayed; `docs/engine/spec.md` records it as something for the schema to
#:   change before the interpreter is written.
EVENTS = (
    "play_self", "conquer", "move", "attack", "hold", "play_other", "defend",
    "die", "beginning_phase", "win_combat", "discard_trigger",
    "end_of_turn", "targeted", "as_played", "become_state", "readied",
    "reveal_trigger", "stunned",
)

#: Zones an ability may function in (365-366, 384-385). `any` is 366.2.a's "at
#: all times in any zone from which the card with the ability can be played".
BOARD, HAND, TRASH, DECK, CHAMPION, BANISHED, CHAIN, ANY = (
    "board", "hand", "trash", "deck", "champion", "banished", "chain", "any")
ZONES = (BOARD, HAND, TRASH, DECK, CHAMPION, BANISHED, CHAIN, ANY)

#: 726-727's Dependent Keywords, and nothing else. 135.2.e.7.b makes only a
#: dependent keyword able to gate an ability, and the DSL refuses a gate on any
#: other keyword — this table is the runtime half of the same refusal.
GATES = ("Legion", "Level", "Empowered")

#: How many triggers one emit may queue before the kernel calls it a loop. A
#: trigger that triggers itself is a legal card and an infinite one is a bug;
#: the bound turns the second into a named failure.
MAX_TRIGGERS = 64


class Gate(object):
    """A Dependent Keyword and its condition (727, 812, 824, 828).

    The ability it introduces is Inactive until the condition is met and Inactive
    again as soon as it stops (727.1.b, 824.1.d) — which is the whole point of
    making this a first-class object rather than folding it into the ability's
    own condition. A condition is checked when a trigger fires; a gate decides
    whether the ability is there to fire at all (721.2).
    """

    __slots__ = ("keyword", "value")

    def __init__(self, keyword, value=0):
        if keyword not in GATES:
            raise RulesError("[%s] is not a Dependent Keyword, so it cannot gate an "
                             "ability (727.1, 135.2.e.7.b)" % (keyword,))
        self.keyword = keyword
        self.value = value

    def label(self):
        return "[%s%s]" % (self.keyword, " %d" % self.value if self.value else "")

    def met(self, g, src):
        """Is the gate's condition true right now?"""
        s = g.s
        seat = src["seat"]
        if self.keyword == "Legion":
            # 812.1.c: as long as a card DIFFERENT from the one with Legion has
            # been Finalized by you this turn. Two finalizations always satisfy
            # it; one satisfies it only if it was not this card's own.
            #
            # Compared by NAME, which is a simplification and the one place this
            # gate is imprecise: a second copy of the same card is a different
            # card and does satisfy 812.1.c, and this reading says it does when
            # there are two finalizations and does not when the one on the board
            # shares its name with the one just played. Comparing the play that
            # created the object would need a permanent to remember which Chain
            # Item put it there, which nothing else in the kernel wants.
            played = s.played[seat]
            return len(played) > 1 or (len(played) == 1 and played[0] != src["name"])
        if self.keyword == "Level":
            # 824.1.c / 824.1.d: while the CONTROLLING player has N or more XP.
            return s.xp[seat] >= self.value
        # 828.1.c: while the Game Object has the Empowered status.
        return bool(src["unit"] and src["unit"]["empowered"])


class Trigger(object):
    """The Condition half of a Triggered Ability (383.2).

    `who` is required rather than inferred, and 383.4.d.2 is why: "When I hold"
    and "When you hold" are the same words, and the first listens only from a
    unit that was present while the second listens from anything referencing the
    player. The census counts the event; only the rules say who is listening.
    """

    __slots__ = ("events", "who", "where", "condition", "frequency")

    def __init__(self, events, who="me", where=None, condition=None, frequency=None):
        events = tuple(events)
        for name in events:
            if name not in EVENTS:
                raise RulesError("%r is not a trigger event this framework detects "
                                 "(383, census 3)" % (name,))
        if who not in ("me", "you", "any", "enemy", "friendly"):
            raise RulesError("%r is not a listener (383.4.c.2, 383.4.d.2)" % (who,))
        if frequency is not None:
            kind, _n, per = frequency
            if kind not in ("nth", "limit") or per not in ("turn", "game", "combat"):
                raise RulesError("%r is not a frequency (383.1.b, 383.3.e)"
                                 % (frequency,))
        self.events = events
        self.who = who
        self.where = where
        self.condition = condition
        self.frequency = frequency

    def matches(self, g, src, event):
        """383.2.c: evaluated AFTER the inciting event has been processed."""
        if event["ev"] not in self.events:
            return False
        if not self._listens(src, event):
            return False
        if self.where is not None and event.get("loc") != self.where:
            return False
        if self.condition is not None and not self.condition(g, src, event):
            # 383.2.a.1: a conditional statement immediately after the Condition
            # is part of the Trigger Condition, not of the Effect — so a false
            # one means the trigger did not happen, rather than a trigger that
            # resolves and does nothing.
            return False
        return True

    def _listens(self, src, event):
        seat, oid = src["seat"], src["oid"]
        if self.who == "any":
            return True
        if self.who == "me":
            return event.get("oid") == oid
        if self.who == "you":
            return event.get("seat") == seat
        if self.who == "enemy":
            return event.get("seat") == 1 - seat
        return event.get("seat") == seat and event.get("oid") != oid


class Cost(object):
    """What an ability charges (201-212, 403-404).

    204.1.b makes the Base Cost of an Activated Ability whatever is written
    before the ":", and 403.1.b.1 makes a Cost within Instructions at the start
    of a Triggered Ability's effect its base cost too — the same object either
    way, which is why one class serves both.
    """

    __slots__ = ("energy", "power", "domains", "exhaust_self", "xp", "extra",
                 "extra_label", "extra_can")

    def __init__(self, energy=0, power=0, domains=(), exhaust_self=False, xp=0,
                 extra=None, extra_can=None, extra_label=""):
        self.energy = energy
        self.power = power
        self.domains = tuple(domains)
        self.exhaust_self = exhaust_self
        self.xp = xp
        #: An arbitrary additional cost (202, 356.2): a callable that performs
        #: it, and one that says whether it can be performed. 203.3 is why both
        #: are needed — a cost that is impossible cannot be paid, and the
        #: ability then cannot be used at all.
        self.extra = extra
        self.extra_can = extra_can
        self.extra_label = extra_label

    def label(self):
        bits = []
        if self.exhaust_self:
            bits.append("[E]")
        if self.energy:
            bits.append("%d Energy" % self.energy)
        if self.power:
            bits.append("%d Power%s" % (self.power,
                                        " (%s)" % "/".join(self.domains)
                                        if self.domains else ""))
        if self.xp:
            bits.append("%d XP" % self.xp)
        if self.extra_label:
            bits.append(self.extra_label)
        return ", ".join(bits) or "no cost"

    def payable(self, g, seat, src):
        """203.3: a cost whose game action is impossible cannot be paid."""
        from . import actions
        s = g.s
        if self.exhaust_self:
            unit = src["unit"]
            if unit is None or unit["exh"]:
                return False
        if self.xp and s.xp[seat] < self.xp:
            return False
        if self.extra_can is not None and not self.extra_can(g, seat, src):
            return False
        if self.energy or self.power:
            return actions.can_pay_cost(g, seat, {
                "energy": self.energy, "power": self.power,
                "domains": list(self.domains), "exact": True})[0]
        return True

    def pay(self, g, seat, src):
        from . import actions
        if self.exhaust_self:
            actions.exhaust(g, src["oid"])
        if self.xp:
            actions.spend_xp(g, seat, self.xp)
        if self.energy or self.power:
            actions.pay_cost(g, seat, {
                "energy": self.energy, "power": self.power,
                "domains": list(self.domains), "exact": True},
                "an activated ability")
        if self.extra is not None:
            self.extra(g, seat, src)


class Ability(object):
    """One ability of one card. Immutable, shared by every clone of a game."""

    __slots__ = ("kind", "cite", "text", "gate", "trigger", "cost", "effect",
                 "presence", "optional", "link", "modifier", "applies",
                 "replace", "unless", "adds", "forbids", "frequency",
                 "owner", "index")

    def __init__(self, kind, text="", cite="", gate=None, trigger=None, cost=None,
                 effect=None, presence=(BOARD,), optional=False, link="",
                 modifier=None, applies=None, replace=None, unless=None,
                 adds=False, forbids=False, frequency=None):
        if kind not in KINDS:
            raise RulesError("%r is not an ability kind (361.1)" % (kind,))
        for zone in presence:
            if zone not in ZONES:
                raise RulesError("%r is not a zone an ability can function in "
                                 "(365-366, 384-385)" % (zone,))
        if kind in ("triggered", "delayed") and trigger is None:
            raise RulesError("a %s ability has a Condition (383.2, 390.2)" % kind)
        self.kind = kind
        self.text = text
        self.cite = cite
        self.gate = gate
        self.trigger = trigger
        self.cost = cost
        self.effect = effect
        self.presence = tuple(presence)
        #: 383.3.a: "you may" as the FIRST part of a Triggered Ability's effect
        #: is decided during finalization, and declining removes it from the
        #: Chain. 383.3.a.3's later "you may" is decided on resolution and is
        #: the effect callable's own business.
        self.optional = optional
        self.link = link
        #: A passive's contribution to the layers: a callable returning partial
        #: effect dicts (see `layers.new_effect`).
        self.modifier = modifier
        #: A replacement's two halves (370.1): does this event qualify, and what
        #: does it become.
        self.applies = applies
        self.replace = replace
        #: "unless [a player] pays [cost]" — asked of that seat on resolution as
        #: a `cost` decision (444, 355.10.c.1).
        self.unless = unless
        #: 400.2/429.2: an ability with the Add action resolves the moment it is
        #: finalized, like a Unit or Gear, and Priority does not pass.
        self.adds = adds
        #: 054.1: this Replacement Effect FORBIDS rather than permits, so it
        #: supersedes any that would allow the same thing. A flag rather than a
        #: guess from the callable, because "can't beats can" is a property of
        #: what the card says and not of what its code happens to return.
        self.forbids = forbids
        #: 371 and 383.3.e are the same modifier on two kinds of ability, so it
        #: has ONE runtime home. The DSL spells it twice — inside `trigger` for
        #: a triggered ability and at ability level for a replacement — and the
        #: hoist below is what makes both spellings arrive here.
        self.frequency = frequency
        if self.frequency is None and trigger is not None:
            self.frequency = trigger.frequency
        self.owner = ""
        self.index = -1

    def __repr__(self):
        return "Ability(%s, %r)" % (self.kind, self.text or self.cite)

    def key(self):
        return (self.owner, self.index)

    def label(self):
        head = self.text or self.kind
        return "%s%s" % ("%s " % self.gate.label() if self.gate else "", head)


# -- the registry --------------------------------------------------------

#: Card data, not game state: name -> the abilities printed on it. The
#: interpreter will fill this from accepted scripts; the tests fill it by hand.
REGISTRY = {}


def register(name, *abilities):
    """Give a card its abilities. Returns their keys, in order."""
    bound = []
    for i, ability in enumerate(abilities):
        ability.owner = name
        ability.index = i
        bound.append(ability)
    links = {}
    for ability in bound:
        if ability.link:
            links.setdefault(ability.link, []).append(ability)
    for link, members in links.items():
        if len(members) < 2:
            # 394: a Linked set is a set with MORE THAN ONE component. A link
            # name with one member is a typo that would otherwise make 397's
            # restriction vacuous for that ability.
            raise RulesError("link %r on %s has one component; Linked Abilities are "
                             "a SET (394)" % (link, name))
    REGISTRY[name] = tuple(bound)
    return [a.key() for a in bound]


def clear():
    """Forget every registered ability. Used between tests, never in a game."""
    REGISTRY.clear()


def of(name):
    return REGISTRY.get(name, ())


def by_key(key):
    owner, index = key
    entry = REGISTRY.get(owner)
    if entry is None or not 0 <= index < len(entry):
        raise RulesError("no ability %r is registered (362)" % (key,))
    return entry[index]


# -- where abilities live (365-366, 384-385) -----------------------------

def sources(g, kinds=None):
    """Every (ability, source) pair whose presence rule puts it in play.

    A "source" is a dict of primitives plus the unit it came from, so a caller
    never has to know whether the ability is on a permanent, a card in a hand,
    or an item on the Chain. Empty and cheap when no card has been scripted,
    which is what keeps a vanilla game at its old throughput.
    """
    if not REGISTRY:
        return ()
    s = g.s
    out = []

    def add(ability, oid, seat, zone, name, unit=None):
        if kinds is not None and ability.kind not in kinds:
            return
        if zone not in ability.presence and ANY not in ability.presence:
            return
        out.append({"key": ability.key(), "ab": ability, "oid": oid, "seat": seat,
                    "zone": zone, "name": name, "unit": unit})

    for unit in s.units:
        for ability in of(unit["name"]):
            add(ability, unit["id"], unit["ctrl"], BOARD, unit["name"], unit)
        # 477.2.a: an ability GRANTED to this object, found through the layer
        # that granted it rather than through a second field on the unit.
        from . import layers
        for owner, index in layers.granted_abilities(unit):
            add(by_key((owner, index)), unit["id"], unit["ctrl"], BOARD,
                unit["name"], unit)

    for bf in s.battlefields:
        for ability in of(bf["name"]):
            # 169: a battlefield sits in the Battlefield Zone, which is part of
            # the Board. Its controller is whoever controls it, and None until
            # somebody does — a battlefield ability with a `you` listener has
            # nobody to listen for until then.
            add(ability, "bf:%d" % bf["i"], bf["ctrl"], BOARD, bf["name"])

    for zone in (HAND, TRASH, CHAMPION, BANISHED, DECK):
        pile = getattr(s, {HAND: "hand", TRASH: "trash", CHAMPION: "champion",
                           BANISHED: "banished", DECK: "main_deck"}[zone])
        # 303.2.a, like every other loop over both players in this kernel. The
        # order of this list decides which of two equal replacements is offered
        # first and which seat's triggers are queued first, so a loop over seat
        # NUMBERS bakes the labels into the order of events and the mirror test
        # fails for a reason that has nothing to do with the rule being tested.
        for seat in s.turn_order():
            for name in pile[seat]:
                for ability in of(name):
                    add(ability, "", seat, zone, name)

    for item in s.chain:
        for ability in of(item["name"]):
            add(ability, item["id"], item["ctrl"], CHAIN, item["name"])
    return out


def active(g, src):
    """Is this ability applying at all (720-725, 727)?

    721.2 is the rule the whole framework rests on: Inactive abilities do not
    trigger, do not apply, and cannot be activated. 727.1.b makes a Dependent
    Ability Inactive until its keyword's condition is met, so the gate is asked
    here and nowhere else.
    """
    gate = src["ab"].gate
    return gate is None or gate.met(g, src)


def stamp_key(src):
    """The key one ability on one object keeps its Timestamp under."""
    return "%s#%s#%d" % (src["oid"], src["key"][0], src["key"][1])


def refresh_stamps(g):
    """480.1/480.2: a Timestamp for every ability that is currently applying.

    EVERY ability, not only the passives that contribute to the layers. 480.1
    says a Timestamp is established "when an effect begins applying", and 372's
    tie-break between two Replacement Effects with the same controller falls
    through to 480.3 — so a replacement with no Timestamp is a replacement whose
    order is whatever the walk that found it happened to be. That is what this
    used to be, and two same-seat replacements then applied in registration
    order rather than in the order they arrived.

    480.2 is the other half: text that becomes Inactive loses its Timestamp, and
    a new one is established when it ceases to be. So entries LEAVE this dict.
    """
    s = g.s
    if not REGISTRY:
        s.stamps.clear()
        return
    live = set()
    for src in sources(g):
        if not active(g, src):
            continue
        key = stamp_key(src)
        live.add(key)
        if key not in s.stamps:
            s.stamp += 1
            s.stamps[key] = s.stamp
    for gone in [k for k in s.stamps if k not in live]:
        del s.stamps[gone]


def passive_effects(g):
    """What every active Passive Ability contributes to the layers (473-480).

    Re-derived on each recomputation rather than stored, which is what makes a
    gate continuous: the turn `[Level 6]` stops holding, the passive is simply
    not in this list and its +Might is gone with it.

    The Timestamps are `refresh_stamps`'s, taken once per recomputation before
    the traits are reset — this runs several times inside one and must not
    invent a new one each pass.
    """
    if not REGISTRY:
        return []
    s = g.s
    out = []
    for src in sources(g, kinds=("passive",)):
        if src["ab"].modifier is None or not active(g, src):
            continue
        key = stamp_key(src)
        ts = s.stamps.get(key, 0)
        from . import layers
        for i, partial in enumerate(src["ab"].modifier(g, src) or ()):
            effect = {"id": "%s/%d" % (key, i), "ts": ts,
                      "layer": layers.LAYER_OF[partial["op"]],
                      "n": 0, "kw": "", "src": src["oid"], "ctrl": src["seat"],
                      "targets": (), "until": "permanent", "ev": ""}
            effect.update(partial)
            effect["targets"] = tuple(effect["targets"])
            out.append(effect)
    return out


# -- events and triggers (382-388) ---------------------------------------

def emit(g, ev, leaving=None, **data):
    """383.2.c: the moment after an inciting event has been processed.

    Every caller is a rule that has just finished doing something — `to_trash`
    after the unit has gone, `score` after the point is taken — because a
    condition evaluated before the event has happened reads the board the event
    was supposed to change.

    `leaving` is 383.2.c.1's other half: a copy of a Game Object that left the
    Board as part of this very event, whose abilities are still evaluated. 808's
    Deathknell is the case that matters, and without it "when I die" is an
    ability that can never fire, because by the time the event exists the object
    that has it is gone.
    """
    if ev not in EVENTS:
        raise RulesError("%r is not a trigger event (383, census 3)" % (ev,))
    event = dict(data)
    event["ev"] = ev
    from . import layers
    # An `until_event` continuous effect ends when its event happens (477).
    layers.expire(g, "until_event", ev)
    if not REGISTRY:
        return event
    _fire_delayed(g, event)
    _fire_triggers(g, event, leaving)
    return event


def leaving_sources(g, gone):
    """The triggered abilities of an object that has just left the Board.

    383.2.c.2 refuses this in general — an object cannot evaluate a trigger from
    a zone it is leaving — and 383.2.c.1 plus 808 carve out the case where the
    LEAVING IS the condition. So this is only ever reached from the event that
    removed the object, and only its own `who="me"` abilities can match.
    """
    out = []
    for ability in of(gone["name"]):
        if ability.kind != "triggered":
            continue
        out.append({"key": ability.key(), "ab": ability, "oid": gone["id"],
                    "seat": gone["ctrl"], "zone": BOARD, "name": gone["name"],
                    "unit": gone})
    return out


def entering_sources(g, event):
    """The Replacement Effects of the object that is ENTERING (370.3, 369.3).

    370.3: "if a Game Object has a Replacement Effect that is active in a
    specific zone, it is evaluated and subsequently applied if it enters that
    zone before an event occurs that it could replace." The two commonest
    replacement shapes in the gauntlet are exactly this — `enters_modified`
    (17 cards) and `as_enters` (3) — and both are printed on the card that is
    arriving, which is in no zone any `sources()` walk can see: 340.1 has taken
    it off the Chain and it is not on the Board yet.

    The mirror image of `leaving_sources`, and for the same reason: the moment
    an object changes zone is the one moment its own text has to be read from
    somewhere other than a zone.
    """
    out = []
    for ability in of(event.get("name", "")):
        if ability.kind not in ("enters_modified", "as_enters", "instead", "would"):
            continue
        out.append({"key": ability.key(), "ab": ability, "oid": "",
                    "seat": event.get("seat"), "zone": BOARD,
                    "name": event.get("name", ""), "unit": None})
    return out


def _fire_triggers(g, event, leaving=None):
    found = 0
    pool = list(sources(g, kinds=("triggered",)))
    if leaving is not None:
        pool.extend(leaving_sources(g, leaving))
    for src in pool:
        if not active(g, src):
            # 721.2/727.1.c.1: an Inactive Triggered Ability does not have its
            # condition evaluated at all.
            continue
        trigger = src["ab"].trigger
        if not trigger.matches(g, src, event):
            continue
        if not _frequency_ok(g, src):
            continue
        found += 1
        if found > MAX_TRIGGERS:
            raise RulesError("one event queued more than %d triggers (383.3)"
                             % MAX_TRIGGERS)
        _queue(g, src, event, "triggered")
    if found:
        g.need_triggers()


def frequency_key(oid, ability):
    """Where the "each turn" counter for one ability on one object lives.

    Keyed by the OBJECT as well as the ability, because 371.1 and 383.3.e.1 both
    cap an ability rather than a card: two copies of the same unit each get
    their own once-each-turn.
    """
    return "%s|%s|%d|%s" % (oid, ability.owner, ability.index,
                            ability.frequency[2])


def _frequency_ok(g, src):
    """371/383.1.b/383.3.e: "once each turn", "N times", "the Nth time"."""
    if src["ab"].frequency is None:
        return True
    kind, n, _per = src["ab"].frequency
    key = frequency_key(src["oid"], src["ab"])
    seen = g.s.used.get(key, 0)
    if kind == "limit":
        # 383.3.e.1: if it has already been performed that many times, it does
        # not trigger. "Performed" is counted at FINALIZATION (`limit_ok` and
        # `_count_performed` below), so this refuses a condition met after the
        # cap is spent — and `finalize` refuses one met BEFORE it was spent but
        # finalized after, which is the case this test alone cannot see.
        return seen < n
    # 383.1.b: "the Nth time". The count moves every time the condition is met,
    # and only the Nth one triggers.
    g.s.used[key] = seen + 1
    return seen + 1 == n


def limit_ok(g, oid, ability):
    """383.3.e.1 again, asked at the moment the ability would be performed.

    The trigger-time check is not enough on its own and the rule says why: the
    cap is on how many times the ability is PERFORMED, and two conditions can be
    met before the first instance has been. Both queue — at trigger time neither
    has been performed — and the second has to find the allowance spent when it
    reaches the front of the Chain.
    """
    if ability.frequency is None or ability.frequency[0] != "limit":
        return True
    _kind, n, _per = ability.frequency
    return g.s.used.get(frequency_key(oid, ability), 0) < n


def _queue(g, src, event, sub):
    """Record a Triggered Ability that has triggered (383.3), not yet on the Chain."""
    s = g.s
    s.trigs.append({
        "id": s.mint("t"), "ctrl": src["seat"], "abil": src["key"],
        "src_id": src["oid"], "name": src["name"], "sub": sub,
        "ev": _flat_event(event),
    })
    g.note("  %s triggers: %s (383.3)" % (src["name"], src["ab"].label()),
           seat=src["seat"])


def _flat_event(event):
    """The triggering event as a hashable tuple, so it can live on the Chain.

    359.3.f.3: information a triggered ability references from its trigger
    condition is checked WHEN THE CONDITION IS FULFILLED, so the event has to be
    carried to resolution rather than re-read there.
    """
    return tuple(sorted((k, v) for k, v in event.items()
                        if isinstance(v, (str, int, bool, type(None)))))


def event_of(item):
    """The triggering event of a chain item, back as a dict."""
    return dict(item.get("ev") or ())


def put_triggers_on_chain(g):
    """383.3.d/383.3.d.1: each controller orders their own, in Turn Order.

    One `order` decision per step rather than one per permutation: "which of
    these three goes on next" asked three times is 3+2+1 options, where the
    product of whole orderings is 6 and grows as a factorial. Same grouping rule
    the rest of the decision API follows.
    """
    s = g.s
    while s.trigs:
        seat = next((x for x in s.turn_order()
                     if any(t["ctrl"] == x for t in s.trigs)), None)
        mine = [t for t in s.trigs if t["ctrl"] == seat]
        if len(mine) > 1:
            s.choosing = {"what": "order_triggers", "seat": seat}
            g.ask(seat, "order",
                  [Option(("next", t["id"]),
                          "put %s's trigger on the Chain next" % t["name"])
                   for t in mine],
                  prompt="seat %d orders the abilities that triggered at the same "
                         "time (383.3.d)" % seat)
            return
        trigger_to_chain(g, mine[0]["id"])


def trigger_to_chain(g, trig_id):
    """400/401: the ability becomes a Pending Item, and that Closes the State."""
    s = g.s
    record = next(t for t in s.trigs if t["id"] == trig_id)
    s.trigs.remove(record)
    ability = by_key(record["abil"])
    item = {"id": s.mint("c"), "ctrl": record["ctrl"], "name": record["name"],
            "kind": "ability", "pending": True, "loc": "", "src": "ability",
            "abil": record["abil"], "src_id": record["src_id"],
            "ev": record["ev"], "sub": record["sub"], "step": 2}
    s.chain.append(item)
    # 401.1: the Chain Item has no card representing it, and it still Closes the
    # State. 339.1: adding to the Chain breaks any sequence of passes.
    s.passes = 0
    g.note("%s's %s ability goes on the Chain [%s] — pending (401.1)"
           % (record["name"], ability.kind, item["id"]), seat=record["ctrl"])
    g.need_cleanup()
    return item


# -- activated abilities (376-381) ---------------------------------------

def activatable(g, seat):
    """What `seat` may activate right now (378, 380, 381).

    381 is the whole of the timing in this slice: an Activated Ability can only
    be activated on its controller's turn and during an Open State, and the Main
    Phase is the only Neutral Open State the Turn Player is asked in.
    """
    if not REGISTRY:
        return []
    s = g.s
    if s.is_closed() or s.is_showdown():
        return []
    out = []
    for src in sources(g, kinds=("activated",)):
        if src["seat"] != seat or seat != s.turn_player:
            continue
        if src["zone"] != BOARD:
            # 380: activated abilities can primarily be activated while on the
            # Board. An ability that says otherwise says so in its presence.
            continue
        if not active(g, src):
            continue                                       # 721.2
        cost = src["ab"].cost
        if cost is not None and not cost.payable(g, seat, src):
            continue                                       # 402.3
        out.append(src)
    return out


def activate(g, seat, oid, key):
    """377.3.a: declare the activation; the ability goes on the Chain."""
    s = g.s
    src = next((x for x in activatable(g, seat)
                if x["oid"] == oid and x["key"] == tuple(key)), None)
    if src is None:
        raise RulesError("seat %d cannot activate %r on %r right now (381)"
                         % (seat, key, oid))
    item = {"id": s.mint("c"), "ctrl": seat, "name": src["name"],
            "kind": "ability", "pending": True, "loc": "", "src": "ability",
            "abil": src["key"], "src_id": oid, "ev": (), "sub": "activated",
            "step": 2}
    s.chain.append(item)
    s.passes = 0
    g.note("seat %d activates %s: %s [%s] (377.3.a)"
           % (seat, src["name"], src["ab"].label(), item["id"]), seat=seat)
    g.need_cleanup()
    return item


# -- playing an ability (398-406) ----------------------------------------

def finalize(g, item):
    """398-406, resumable. True when the item is ready to stop being Pending.

    False means either a decision is now pending (402.1's "you may", 404.2's
    decline) or the item has left the Chain. The steps are numbered as 401-406
    number them and `item["step"]` carries the progress, because two of them ask
    the controller a question and the kernel has to be able to come back.
    """
    ability = by_key(item["abil"])
    seat = item["ctrl"]
    src = _src_of(g, item)

    if item["step"] <= 2:
        # 402.1 / 383.3.a: "you may" as the first part of a Triggered Ability's
        # effect is decided HERE, and 402.1.a removes it from the Chain if the
        # controller declines. An activated ability is already a choice (378),
        # so this is only asked of the kinds that arrived on their own.
        if ability.optional and item["sub"] != "activated":
            g.s.choosing = {"what": "finalize_may", "item": item["id"]}
            g.ask(seat, "optional",
                  [Option(("do",), "perform %s" % ability.label()),
                   Option(("skip",), "decline it — it leaves the Chain (402.1.a)")],
                  prompt="seat %d may perform %s (383.3.a)"
                         % (seat, ability.label()))
            item["step"] = 3
            return False
        item["step"] = 3

    if item["step"] <= 4:
        cost = ability.cost
        if cost is not None:
            if not cost.payable(g, seat, src):
                # 403/404 with an unpayable cost: a Triggered Ability leaves the
                # Chain (404.2) and never becomes a Finalized Chain Item.
                return _abandon(g, item, "its cost cannot be paid (404.2, 203.3)")
            if item["sub"] != "activated":
                # 404.2: players MAY decline to pay for a Triggered Ability that
                # has incurred a cost. An activated ability's cost was accepted
                # when it was activated (378), so only this side is asked.
                g.s.choosing = {"what": "finalize_cost", "item": item["id"]}
                g.ask(seat, "cost",
                      [Option(("pay",), "pay %s" % cost.label()),
                       Option(("decline",),
                              "decline — the ability leaves the Chain (404.2)")],
                      prompt="seat %d may pay %s for %s (404.2)"
                             % (seat, cost.label(), ability.label()))
                item["step"] = 5
                return False
            cost.pay(g, seat, src)
        item["step"] = 5

    # 405: check legality. 402.4 is the sibling rule — a Triggered Ability with
    # no legal choices left leaves the Chain, and 402.4.a says that is not being
    # countered.
    if ability.applies is not None and not ability.applies(g, {"ev": ""}, src):
        return _abandon(g, item, "it has no legal choices left (402.4)")
    if not limit_ok(g, item["src_id"], ability):
        # 383.3.e.1: another instance of this same ability has already been
        # performed the permitted number of times this turn, which it had not
        # been when this one triggered.
        return _abandon(g, item, "its \"once each turn\" has already been "
                                 "performed this turn (383.3.e.1)")
    _count_performed(g, item["src_id"], ability)
    item["step"] = 6
    return True


def resume_finalize(g, item, key):
    """Continue `finalize` after the controller answered one of its questions."""
    what = g.s.choosing["what"] if g.s.choosing else ""
    g.s.choosing = None
    ability = by_key(item["abil"])
    if what == "finalize_may":
        if key[0] == "skip":
            # 383.3.a.2: it is removed from the Chain and considered NOT to have
            # triggered — so its "once each turn" count is untouched.
            _abandon(g, item, "its controller declined to perform it (383.3.a.2)")
            return
    elif what == "finalize_cost":
        if key[0] == "decline":
            _abandon(g, item, "its controller declined to pay (404.2)")
            return
        ability.cost.pay(g, item["ctrl"], _src_of(g, item))


def _abandon(g, item, why):
    """402.4/404.2: the item leaves the Chain without ever being finalized."""
    from . import chain
    s = g.s
    s.chain.remove(item)
    g.note("  %s [%s] leaves the Chain — %s. This is not being countered "
           "(402.4.a, 404.2.a)" % (item["name"], item["id"], why),
           seat=item["ctrl"])
    g.need_cleanup()
    chain.after_leaving(g)
    return False


def resolve(g, item):
    """406.5: execute the ability, just like a Spell.

    An ability with an "unless [someone] pays" clause stops here and asks that
    seat a `cost` decision; the rest of the effect runs when it is answered,
    with whether they paid in the context.
    """
    ability = by_key(item["abil"])
    src = _src_of(g, item)
    ctx = {"seat": item["ctrl"], "src": src, "item": dict(item),
           "ev": event_of(item), "paid": None}
    if ability.unless is not None:
        seat, cost, why = ability.unless
        target = item["ctrl"] if seat == "you" else 1 - item["ctrl"]
        if not cost.payable(g, target, src):
            g.note("  seat %d cannot pay %s, so %s happens (203.3)"
                   % (target, cost.label(), why), seat=target)
            ctx["paid"] = False
            ability.effect(g, ctx)
            return
        g.s.choosing = {"what": "unless_pays", "abil": list(item["abil"]),
                        "src_id": item["src_id"], "seat": target,
                        "ctrl": item["ctrl"], "ev": item["ev"]}
        g.ask(target, "cost",
              [Option(("pay",), "pay %s" % cost.label()),
               Option(("decline",), why)],
              prompt="seat %d pays %s, or %s (444, 355.10.c.1)"
                     % (target, cost.label(), why))
        return
    ability.effect(g, ctx)


def finish_unless(g, choice, key):
    """The other half of an "unless ... pays": run the effect either way."""
    ability = by_key(tuple(choice["abil"]))
    _seat, cost, _why = ability.unless
    target = choice["seat"]
    src = _src_by_id(g, choice["src_id"], choice["ctrl"])
    paid = key[0] == "pay"
    if paid:
        cost.pay(g, target, src)
        g.note("  seat %d pays %s (203)" % (target, cost.label()), seat=target)
    else:
        g.note("  seat %d declines to pay %s (203.3)" % (target, cost.label()),
               seat=target)
    ability.effect(g, {"seat": choice["ctrl"], "src": src, "item": None,
                       "ev": dict(choice["ev"] or ()), "paid": paid})


def _count_performed(g, oid, ability):
    """383.3.e.1's "performed", counted at the moment it actually is.

    Which is finalization (406.1), not resolution: 404.2 lets a controller
    decline to pay and 383.3.a.2 lets them decline a "you may", and an ability
    that left the Chain either way was never performed. Everything past
    finalization happens.
    """
    if ability.frequency is None or ability.frequency[0] != "limit":
        return
    key = frequency_key(oid, ability)
    g.s.used[key] = g.s.used.get(key, 0) + 1


def _src_of(g, item):
    return _src_by_id(g, item["src_id"], item["ctrl"])


def _src_by_id(g, oid, seat):
    """The source record for an ability already on the Chain.

    392 is why this tolerates an object that is gone: a Delayed Ability executes
    when its time comes "regardless of whether the source of the Delayed Ability
    is still on the board or not", and 808's Deathknell resolves from a unit
    that is by definition no longer there.
    """
    unit = next((u for u in g.s.units if u["id"] == oid), None)
    name = unit["name"] if unit else ""
    return {"key": None, "ab": None, "oid": oid, "seat": seat,
            "zone": BOARD, "name": name, "unit": unit}


def target(g, seat, oids, what=""):
    """355.6/355.7: choosing specific Game Objects TARGETS them (383.4.b).

    383.4.b.2 puts the Targeting Effects on the Chain "after a spell or ability
    that targets an appropriate Game Object is Finalized", and 754 raises them
    again when 750's new choices name an object that was not targeted before -
    both of which are this function, called from wherever the choice was made.
    """
    for oid in oids:
        unit = next((u for u in g.s.units if u["id"] == oid), None)
        emit(g, "targeted", oid=oid, seat=seat,
             name=unit["name"] if unit else "", by=seat, what=what)
    return tuple(oids)


# -- reflexive triggers (386-388) ----------------------------------------

def reflex(g, ctx, key, times=1):
    """387/388: create N new Pending Items on the Chain, in order.

    388.2 is the shape: they are all added, and none of them goes beyond the
    first step of playing until the ones after it are on too — which is exactly
    what 337.1's "finalize the OLDEST pending item" then does for free.
    """
    ability = by_key(key)
    if ability.kind != "reflexive":
        raise RulesError("%r is not a Reflexive Trigger (387)" % (key,))
    s = g.s
    made = []
    for _ in range(times):
        item = {"id": s.mint("c"), "ctrl": ctx["seat"], "name": ctx["src"]["name"],
                "kind": "ability", "pending": True, "loc": "", "src": "ability",
                "abil": key, "src_id": ctx["src"]["oid"],
                "ev": _flat_event(ctx["ev"]), "sub": "reflexive", "step": 2}
        s.chain.append(item)
        made.append(item)
    s.passes = 0
    g.note("  a Reflexive Trigger adds %d Pending Item(s) to the Chain (388.1, "
           "387.1.a)" % times, seat=ctx["seat"])
    g.need_cleanup()
    return made


# -- delayed abilities (389-392) -----------------------------------------

#: The windows a Delayed Ability may be keyed to. 390.2's "a specific frame of
#: time", closed so that a window nobody implemented is a refusal rather than an
#: ability that silently never fires.
WINDOWS = ("next", "this_turn", "end_of_turn")


def delay(g, seat, key, event, window="this_turn", src_id=""):
    """389-392: create a Delayed Ability keyed to a window.

    392 puts it on the state and not on its source: it executes when its
    condition and specified time occur "regardless of whether the source of the
    Delayed Ability is still on the board or not".
    """
    ability = by_key(key)
    if ability.kind != "delayed":
        raise RulesError("%r is not a Delayed Ability (390)" % (key,))
    if window not in WINDOWS:
        raise RulesError("%r is not a window a Delayed Ability can name (390.2)"
                         % (window,))
    if event not in EVENTS:
        raise RulesError("%r is not a trigger event (383, 390.2)" % (event,))
    s = g.s
    record = {"id": s.mint("d"), "ctrl": seat, "abil": key, "ev": event,
              "window": window, "src_id": src_id, "turn": s.turn}
    s.delayed.append(record)
    g.note("  a Delayed Ability is created: %s, %s (389, 391)"
           % (ability.label(), window), seat=seat)
    return record


def _fire_delayed(g, event):
    """391: a Delayed Ability resolves like the ability it augments.

    `next` fires once and is gone (390.3's "the next time"); a window that lasts
    the turn stays until 317.2.d retires it.
    """
    s = g.s
    for record in list(s.delayed):
        if record["ev"] != event["ev"]:
            continue
        src = {"key": record["abil"], "ab": by_key(record["abil"]),
               "oid": record["src_id"], "seat": record["ctrl"],
               "zone": BOARD, "name": _name_of(g, record["src_id"]),
               "unit": next((u for u in s.units if u["id"] == record["src_id"]), None)}
        trigger = src["ab"].trigger
        if not trigger.matches(g, src, event):
            continue
        if record["window"] == "next":
            # 390.3's "the next time": spent by firing. A window that lasts a
            # turn is not — 391 keeps a Delayed Ability active "during the
            # specified time", and 317.2.d is what closes it.
            s.delayed.remove(record)
        _queue(g, src, event, "delayed")
        g.need_triggers()


def _name_of(g, oid):
    unit = next((u for u in g.s.units if u["id"] == oid), None)
    return unit["name"] if unit else "a delayed ability"


def retire_delayed(g, window):
    """317.2.d: a window that lasts "this turn" closes with the turn."""
    s = g.s
    gone = [d for d in s.delayed if d["window"] == window]
    for record in gone:
        s.delayed.remove(record)
    if gone:
        g.note("%d Delayed Ability window(s) close (317.2.d, 391)" % len(gone))
    return bool(gone)


# -- linked abilities (393-397) ------------------------------------------

def link_record(g, ctx, oids):
    """394.1: record which Game Objects this component of a Linked set affected."""
    ability = _ability_of(ctx)
    if not ability.link:
        raise RulesError("%r is not part of a Linked set (394)" % (ability,))
    key = "%s#%s#%s" % (ctx["src"]["oid"], ability.owner, ability.link)
    g.s.links[key] = tuple(oids)
    return g.s.links[key]


def linked_objects(g, ctx):
    """397: what a component Linked Ability is allowed to interact with.

    "A component Linked Ability that references a Game Object affected by
    another Ability in the set may only interact with Game Objects affected by
    the Abilities it is Linked with." An empty tuple means the earlier component
    affected nothing, and 359.3.e.14.a then makes this one do nothing too.
    """
    ability = _ability_of(ctx)
    if not ability.link:
        raise RulesError("%r is not part of a Linked set (394)" % (ability,))
    key = "%s#%s#%s" % (ctx["src"]["oid"], ability.owner, ability.link)
    return g.s.links.get(key, ())


def _ability_of(ctx):
    item = ctx.get("item")
    if item is None:
        raise RulesError("a Linked Ability needs the Chain Item it came from (394)")
    return by_key(tuple(item["abil"]))


# -- the log -------------------------------------------------------------

def describe(g, unit):
    """Every ability on a unit and whether it is Active, for the log."""
    out = []
    for src in sources(g):
        if src["oid"] != unit["id"]:
            continue
        state = "active" if active(g, src) else "INACTIVE (721.2)"
        out.append("%s — %s" % (src["ab"].label(), state))
    return out

