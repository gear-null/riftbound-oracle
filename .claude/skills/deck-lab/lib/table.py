"""The table: zones, phases, resources, combat and scoring for 1v1 Duel.

This is a tabletop, not a player. It does everything that must not be imagined —
shuffling, drawing, what is in which zone, whose turn it is, what a rune pool
holds, how much damage a combat assigns, who scored and when — and it decides
nothing that a player decides.

It also never interprets card text. When a card is played its printed text is
surfaced verbatim and the effect is applied by the reader through the same
primitive actions the rules define (413-444), so the resulting log is a record
of physical operations rather than of a narrative.

Everything random goes through one seeded generator, so a game replays exactly.
"""
import random

import cards
from deckfile import MODE

# Phases of a turn (314-317).
AWAKEN, BEGINNING, CHANNEL, DRAW, MAIN, ENDING = (
    "awaken", "beginning", "channel", "draw", "main", "ending",
)
TURN_PHASES = (AWAKEN, BEGINNING, CHANNEL, DRAW, MAIN, ENDING)

BASE = "base"
BATTLEFIELD = "bf"


class RulesError(Exception):
    """An action the rules do not allow. Raised instead of quietly proceeding."""


def _id_number(oid):
    """The numeric part of an object id like `u12`, or 0 if it has none."""
    digits = "".join(ch for ch in str(oid) if ch.isdigit())
    return int(digits) if digits else 0


def _jsonable_rng(state):
    """`random.getstate()` as JSON: its middle element is a tuple of 625 ints."""
    version, internal, gauss = state
    return [version, list(internal), gauss]


def _rng_from_json(raw):
    version, internal, gauss = raw
    return (version, tuple(internal), gauss)


class Permanent:
    """A unit or gear on the board (140, 147)."""

    __slots__ = ("id", "name", "controller", "owner", "location", "exhausted",
                 "damage", "buffs", "attached_to", "note")

    def __init__(self, oid, name, controller, location):
        self.id = oid
        self.name = name
        self.controller = controller
        self.owner = controller
        self.location = location
        self.exhausted = False
        self.damage = 0
        self.buffs = 0
        self.attached_to = None
        #: Free-text marker for a state the engine does not model (stunned,
        #: a granted keyword). Carried and shown, never acted on.
        self.note = ""

    @property
    def base_might(self):
        return cards.might(self.name) or 0

    @property
    def might(self):
        """Printed Might plus buffs (703). Damage does not reduce Might."""
        return self.base_might + self.buffs

    @property
    def is_unit(self):
        return cards.card_type(self.name) == cards.UNIT

    def as_dict(self):
        return {k: getattr(self, k) for k in self.__slots__}


class Rune:
    """A channeled rune on the board (161.1.a — on the board, not a permanent)."""

    __slots__ = ("id", "name", "controller", "exhausted")

    def __init__(self, oid, name, controller, exhausted=False):
        self.id = oid
        self.name = name
        self.controller = controller
        self.exhausted = exhausted

    @property
    def domain(self):
        d = cards.domains(self.name)
        return d[0] if d else None

    def as_dict(self):
        return {k: getattr(self, k) for k in self.__slots__}


class Battlefield:
    """A battlefield in the Battlefield Zone (169), and who holds it (190)."""

    __slots__ = ("index", "name", "provided_by", "controller", "contested",
                 "contested_by", "scored_by")

    def __init__(self, index, name, provided_by):
        self.index = index
        self.name = name
        self.provided_by = provided_by
        self.controller = None
        self.contested = False
        #: The seat whose unit applied Contested. 464.2.c.1 makes that player
        #: the Attacker, and 323.11 makes contested removal depend on whether
        #: they still have units here — neither is recoverable from a bool.
        self.contested_by = None
        #: Seats that have already Scored here this turn (470).
        self.scored_by = set()

    @property
    def location(self):
        return f"{BATTLEFIELD}:{self.index}"

    def as_dict(self):
        d = {k: getattr(self, k) for k in self.__slots__}
        d["scored_by"] = sorted(d["scored_by"])
        return d


class Player:
    __slots__ = ("seat", "name", "legend", "champion_zone", "main_deck", "rune_deck",
                 "hand", "trash", "banished", "points", "energy", "power", "deck")

    def __init__(self, seat, deck):
        self.seat = seat
        self.deck = deck
        self.name = deck.name
        self.legend = deck.legend
        #: The Chosen Champion, placed here at setup (112). Not in the deck.
        self.champion_zone = [deck.chosen_champion] if deck.chosen_champion else []
        self.main_deck = []
        self.rune_deck = []
        self.hand = []
        self.trash = []
        self.banished = []
        self.points = 0
        #: Rune Pool (165-167). Energy is domainless; Power carries a domain.
        self.energy = 0
        self.power = {}

    def power_total(self):
        return sum(self.power.values())

    def as_dict(self):
        return {
            "seat": self.seat, "name": self.name, "legend": self.legend,
            "champion_zone": list(self.champion_zone), "hand": list(self.hand),
            "main_deck": list(self.main_deck), "rune_deck": list(self.rune_deck),
            "trash": list(self.trash), "banished": list(self.banished),
            "points": self.points, "energy": self.energy, "power": dict(self.power),
        }


class Table:
    """One game in progress."""

    def __init__(self, decks, seed, mode=MODE, first=None):
        if len(decks) != 2:
            raise RulesError("1v1 Duel seats exactly two players (485.1)")
        self.mode = mode
        self.seed = seed
        #: The shared stream: things that belong to the game rather than a seat
        #: (who goes first).
        self.rng = random.Random(seed)
        #: One stream per seat, derived from the seed alone.
        #:
        #: A single shared generator made a seat's shuffle depend on what the
        #: OTHER seat was playing: both shuffles were drawn from one stream, so
        #: the opponent's deck order was a function of how many numbers your
        #: deck's shuffle had consumed. With equal-length decks that happened to
        #: pair the two arms perfectly; with a 39-card list against a 40-card one
        #: it silently unpaired them. Neither property was chosen, and the run
        #: that exposed it read 18 games as independent when they were six
        #: situations played three times.
        #:
        #: Deriving per seat makes the pairing DELIBERATE: at a fixed seed a
        #: seat always draws the same cards, whatever it is facing, so two decks
        #: can be compared over identical opposition. Independent samples come
        #: from distinct seeds, not from replaying one.
        self.seat_rng = [random.Random(f"{seed}/seat{i}") for i in range(2)]
        self.players = [Player(0, decks[0]), Player(1, decks[1])]
        self.battlefields = []
        self.permanents = []
        self.runes = []
        self.chain = []
        self.turn = 0
        self.phase = None
        self.turn_player = 0
        #: Set once, so the extra first-turn rune (485.7) is granted once.
        self.first_player = first
        self.second_player_channel_bonus_used = False
        self.winner = None
        #: The Victory Score in force (485.3), mutable because battlefields and
        #: cards change it — "Aspirant's Climb" reads "Increase the points
        #: needed to win the game by 1", and a table that kept 8 hard-coded
        #: would declare a winner a full point early.
        self.victory_target = mode["victory_score"]
        self.log = []
        #: Cards whose printed text has already been put in front of the reader
        #: this game. Re-printing it on every render was ~48% of a turn's output
        #: and told them nothing they had not just been told.
        self.text_shown = set()
        self._next_id = 1
        self.setup_done = False

    # -- identity --------------------------------------------------------

    def _oid(self, prefix):
        """A fresh object id. Never one already on the board.

        The counter is derived on load, so this is belt and braces — but an id
        collision is silent and mis-targets a kill, which is the kind of defect
        worth two guards.
        """
        taken = {o.id for o in self.permanents + self.runes}
        while True:
            oid = f"{prefix}{self._next_id}"
            self._next_id += 1
            if oid not in taken:
                return oid

    def note(self, message, private_to=None, detail=""):
        """Record something that happened.

        `private_to` marks an entry as visible only to that seat — a draw names
        cards, and rule 108.7.c makes a hand Private Information. The entry is
        still recorded in full so the game can be reviewed afterwards; `detail`
        carries the part a seat view redacts.
        """
        entry = {"turn": self.turn, "phase": self.phase, "text": message}
        if private_to is not None:
            entry["private_to"] = private_to
            entry["detail"] = detail
        self.log.append(entry)
        return message

    def first_sight(self, name):
        """True the first time a card's text is worth printing this game."""
        if name in self.text_shown:
            return False
        self.text_shown.add(name)
        return True

    def player(self, seat):
        return self.players[seat]

    def opponent(self, seat):
        return 1 - seat

    # -- setup (110-118) -------------------------------------------------

    def setup(self):
        """Run the setup process, up to but not including mulligans."""
        if self.setup_done:
            raise RulesError("setup has already run")
        if self.first_player is None:
            # 115: any fair random method. Seeded, so the game replays.
            self.first_player = self.rng.randrange(2)
        self.turn_player = self.first_player

        for p in self.players:
            p.main_deck = list(p.deck.main_cards())
            p.rune_deck = list(p.deck.rune_cards())
            # 114: shuffled separately, and on this seat's own stream so the
            # order does not depend on what the opponent brought.
            self.seat_rng[p.seat].shuffle(p.main_deck)
            self.seat_rng[p.seat].shuffle(p.rune_deck)

        # 485.5: each player randomly selects one of their three battlefields.
        for p in self.players:
            provided = p.deck.battlefield_cards()
            if not provided:
                raise RulesError(f"seat {p.seat} provided no battlefields (103.4)")
            chosen = self.seat_rng[p.seat].choice(provided)
            self.battlefields.append(Battlefield(len(self.battlefields), chosen, p.seat))

        # 116: players each draw 4.
        for p in self.players:
            self.draw(p.seat, self.mode["opening_hand"], reason="opening hand")

        self.setup_done = True
        self.note(
            f"setup: seat {self.first_player} goes first; battlefields "
            + " and ".join(b.name for b in self.battlefields)
        )
        # Battlefield text is in force from turn one and is easy to forget,
        # since nothing prompts for it later. It is surfaced now, once, and
        # applied by the reader — including anything that moves the target.
        for bf in self.battlefields:
            if cards.find(bf.name) and cards.text(bf.name).strip():
                self.note(f"  {bf.name} reads: {cards.text(bf.name)}")
        self.note(f"victory score is {self.victory_target} — adjust with `target <n>` if a card changes it")
        return self

    #: 117.1 caps a mulligan at two cards.
    MULLIGAN_MAX = 2

    def mulligan(self, seat, set_aside=None):
        """Perform seat's mulligan (117).

        The arguments are the cards SET ASIDE, not the ones kept — 117.1 puts the
        limit on what you set aside, so keeping is the wrong way round to express
        it. At most two (117.1); draw that many (117.2); and only THEN recycle
        the ones set aside (117.3).

        The order matters and was wrong: shuffling them back before redrawing
        let a card you had just thrown away come straight back, which is not a
        mulligan the rules describe.
        """
        p = self.player(seat)
        set_aside = list(set_aside or [])
        if len(set_aside) > self.MULLIGAN_MAX:
            raise RulesError(
                f"a mulligan sets aside at most {self.MULLIGAN_MAX} cards, "
                f"not {len(set_aside)} (117.1)"
            )
        remaining = list(p.hand)
        for name in set_aside:
            if name not in remaining:
                raise RulesError(f"{name} is not in seat {seat}'s hand")
            remaining.remove(name)
        if not set_aside:
            return self.note(f"seat {seat} keeps their hand")

        # 117.1 set aside, 117.2 draw as many, 117.3 THEN recycle.
        p.hand = remaining
        self.draw(seat, len(set_aside), reason="mulligan")
        p.main_deck.extend(set_aside)
        # 431.2.b: cards recycled together are randomised.
        self.seat_rng[seat].shuffle(p.main_deck)
        return self.note(
            f"seat {seat} mulligans {len(set_aside)}, keeping {len(remaining)}"
        )

    # -- zone movement (the Game Actions of 413-444) ---------------------

    def draw(self, seat, n=1, reason=""):
        """Draw n (413), burning out where the deck runs short (431.1.a)."""
        p = self.player(seat)
        drawn = []
        remaining = n
        # A player whose trash is also empty burns out again on the next attempt
        # (431.3), handing over a point each time until someone wins. The bound
        # is the Victory Score, so this always terminates.
        for _ in range(self.victory_target + 2):
            take = min(remaining, len(p.main_deck))
            for _ in range(take):
                drawn.append(p.main_deck.pop(0))
            remaining -= take
            if remaining <= 0:
                break
            self.burn_out(seat)
            if self.winner is not None:
                break
        p.hand.extend(drawn)
        if drawn:
            # The card names are private to the drawing seat (108.7.c). They used
            # to sit in the public log, and `new` printed that log unfiltered —
            # so both opening hands were on screen before the first mulligan
            # decision, which is the one leak a reader cannot recover from.
            self.note(
                f"seat {seat} draws {len(drawn)}" + (f" ({reason})" if reason else ""),
                private_to=seat,
                detail=", ".join(drawn),
            )
        return drawn

    def burn_out(self, seat):
        """Run the Burn Out sequence (431.2).

        This used to be a log line and nothing else, which made a decked-out
        player immortal: 431.2.c is a point award, and 431.3.a's "burning out
        repeatedly, giving 1 point to an opponent each time, until an opponent
        passes the Victory Score" is the only way such a game ever ends. Twenty
        turns of an empty deck left both players on zero and no winner.

        The caller performs 431.2.a and 431.2.d — as much of the action as
        possible, then the remainder — because only it knows what the action was.
        """
        p = self.player(seat)
        opponent = self.opponent(seat)
        self.note(f"seat {seat} BURNS OUT (431)")

        # 431.2.b: recycle the trash into the Main Deck, randomised.
        if p.trash:
            recycled = len(p.trash)
            p.main_deck.extend(p.trash)
            p.trash = []
            self.seat_rng[seat].shuffle(p.main_deck)
            self.note(f"  seat {seat} recycles {recycled} card(s) from trash into their Main Deck (431.2.b)")
        else:
            self.note(f"  seat {seat}'s trash is empty; the Main Deck stays empty (431.3)")

        # 431.2.c: an opponent gains a point. Not a Score — 471.1's restrictions
        # are about Scoring, and this is a plain point gain.
        self.player(opponent).points += 1
        self.note(f"  seat {opponent} gains 1 point from the burn out → "
                  f"{self.player(opponent).points} (431.2.c)")
        # 431.3.c.1: a win from this is immediate, without waiting for a cleanup.
        self.check_victory()
        return self.player(opponent).points

    def channel(self, seat, n=1, exhausted=False):
        """Channel n runes from the top of the Rune Deck onto the board (430)."""
        p = self.player(seat)
        out = []
        for _ in range(n):
            if not p.rune_deck:
                break  # 430.3: channel as many as possible.
            name = p.rune_deck.pop(0)
            rune = Rune(self._oid("r"), name, seat, exhausted=exhausted)
            self.runes.append(rune)
            out.append(rune)
        if out:
            self.note(
                f"seat {seat} channels {len(out)}"
                + (" exhausted" if exhausted else "")
                + f": {', '.join(r.name for r in out)}"
            )
        elif n:
            self.note(f"seat {seat} cannot channel — Rune Deck is empty")
        return out

    def discard(self, seat, name):
        """Discard from hand to the trash (422)."""
        p = self.player(seat)
        if name not in p.hand:
            raise RulesError(f"{name} is not in seat {seat}'s hand")
        p.hand.remove(name)
        p.trash.append(name)
        return self.note(f"seat {seat} discards {name}")

    def put_into_play(self, seat, name, location=None, exhausted=False, source=None):
        """Put a unit or gear onto the board and return it.

        This is the physical half of playing a card. Paying for it is a separate
        call, because a card can arrive without being paid for and a payment can
        be made for something that is not a card.
        """
        p = self.player(seat)
        if cards.find(name) is None:
            options = cards.candidates(name)
            raise RulesError(
                f"{name!r} is not a card this table knows"
                + (f" — did you mean {', '.join(options)}?" if options else "")
            )
        # A card has to come from somewhere. Accepting one that was in no zone
        # conjured a permanent out of nothing and left the zone it should have
        # come from unchanged — a board state no sequence of legal plays reaches.
        # Effects do put units into play from the trash or the deck, so that is
        # said explicitly rather than left as a hole anything can walk through.
        if source in (None, "hand", "champion") :
            if name in p.hand:
                p.hand.remove(name)
            elif name in p.champion_zone:
                p.champion_zone.remove(name)
            else:
                raise RulesError(
                    f"{name} is not in seat {seat}'s hand or Champion Zone — pass a "
                    "source (trash, main_deck, banished, elsewhere) if an effect is "
                    "putting it into play from somewhere else"
                )
        elif source == "elsewhere":
            # Deliberately unaccounted for: a token, or a zone this table does
            # not model. Logged so the gap is visible in the record.
            self.note(f"seat {seat} puts {name} into play from outside any tracked zone")
        else:
            zone = getattr(p, source, None)
            if zone is None:
                raise RulesError(
                    f"{source!r} is not a zone — use hand, trash, main_deck, "
                    "rune_deck, banished or elsewhere"
                )
            if name not in zone:
                raise RulesError(f"{name} is not in seat {seat}'s {source}")
            zone.remove(name)
        location = location or f"{BASE}:{seat}"
        self._require_location(location)
        perm = Permanent(self._oid("u"), name, seat, location)
        perm.exhausted = exhausted
        self.permanents.append(perm)
        self.note(f"seat {seat} puts {name} [{perm.id}] into play at {self.where(location)}")
        if location.startswith(BATTLEFIELD):
            # 190.3.a.1: arriving at a battlefield you do not control contests it.
            self._apply_contested(perm)
        return perm

    def to_trash(self, oid, reason="killed"):
        """Move a permanent from the board to its owner's trash (428)."""
        perm = self.permanent(oid)
        self.permanents.remove(perm)
        self.player(perm.owner).trash.append(perm.name)
        for other in self.permanents:
            if other.attached_to == perm.id:
                other.attached_to = None
        return self.note(f"{perm.name} [{perm.id}] → trash ({reason})")

    def banish(self, oid):
        """Banish a permanent (427)."""
        perm = self.permanent(oid)
        self.permanents.remove(perm)
        self.player(perm.owner).banished.append(perm.name)
        return self.note(f"{perm.name} [{perm.id}] is banished")

    def play_spell(self, seat, name):
        """Move a spell from hand to the trash, its text left for the reader (157).

        The engine does not execute the spell. It moves the card and prints what
        the card says, so the effect is applied through explicit actions that
        show up in the log.
        """
        p = self.player(seat)
        if name not in p.hand:
            raise RulesError(f"{name} is not in seat {seat}'s hand")
        p.hand.remove(name)
        p.trash.append(name)
        self.note(f"seat {seat} plays {name}")
        return cards.text(name)

    def recycle_card(self, seat, name, from_zone="hand"):
        """Return a card to the bottom of its deck (416)."""
        p = self.player(seat)
        zone = getattr(p, from_zone)
        if name not in zone:
            raise RulesError(f"{name} is not in seat {seat}'s {from_zone}")
        zone.remove(name)
        # 161.2.b: a recycled Rune goes to the Rune Deck, not the Main Deck.
        target = p.rune_deck if cards.card_type(name) == cards.RUNE else p.main_deck
        target.append(name)
        return self.note(f"seat {seat} recycles {name} from {from_zone}")

    # -- board state -----------------------------------------------------

    def permanent(self, oid):
        for perm in self.permanents:
            if perm.id == oid:
                return perm
        raise RulesError(f"no permanent with id {oid!r} on the board")

    def rune(self, oid):
        for r in self.runes:
            if r.id == oid:
                return r
        raise RulesError(f"no rune with id {oid!r} on the board")

    def at(self, location):
        return [p for p in self.permanents if p.location == location]

    def units_at(self, location, seat=None):
        return [
            p for p in self.at(location)
            if p.is_unit and (seat is None or p.controller == seat)
        ]

    def battlefield(self, index):
        try:
            return self.battlefields[int(index)]
        except (IndexError, ValueError):
            raise RulesError(f"no battlefield {index!r}")

    def where(self, location):
        kind, _, idx = location.partition(":")
        if kind == BASE:
            return f"seat {idx}'s base"
        return f"{self.battlefield(idx).name} (bf:{idx})"

    def _require_location(self, location):
        kind, _, idx = location.partition(":")
        if kind == BASE and idx in ("0", "1"):
            return
        if kind == BATTLEFIELD:
            self.battlefield(idx)
            return
        raise RulesError(f"{location!r} is not a location — use base:0/base:1 or bf:0/bf:1")

    # -- exhaust / ready (414, 415) --------------------------------------

    def exhaust(self, oid):
        obj = self._object(oid)
        if obj.exhausted:
            raise RulesError(f"{obj.name} [{oid}] is already exhausted")
        obj.exhausted = True
        return self.note(f"{obj.name} [{oid}] exhausts")

    def ready(self, oid):
        obj = self._object(oid)
        obj.exhausted = False
        return self.note(f"{obj.name} [{oid}] readies")

    def _object(self, oid):
        for obj in self.permanents + self.runes:
            if obj.id == oid:
                return obj
        raise RulesError(f"no object with id {oid!r} on the board")

    # -- resources (163-168) ---------------------------------------------

    def add_energy(self, seat, n=1):
        self.player(seat).energy += n
        return self.note(f"seat {seat} adds {n} Energy")

    def add_power(self, seat, domain, n=1):
        p = self.player(seat)
        p.power[domain] = p.power.get(domain, 0) + n
        return self.note(f"seat {seat} adds {n} {domain} Power")

    def empty_pool(self, seat):
        """Empty a rune pool; unspent Energy and Power are lost (167)."""
        p = self.player(seat)
        lost = (p.energy, dict(p.power))
        p.energy = 0
        p.power = {}
        if lost[0] or lost[1]:
            self.note(f"seat {seat}'s rune pool empties (lost {lost[0]}E, {sum(lost[1].values())}P)")

    def tap_for_energy(self, seat, count=1):
        """Exhaust readied runes for Energy — [E]: Add [1] (164.2.a)."""
        available = [r for r in self.runes if r.controller == seat and not r.exhausted]
        if len(available) < count:
            raise RulesError(
                f"seat {seat} has {len(available)} readied rune(s), needs {count}"
            )
        for rune in available[:count]:
            rune.exhausted = True
        self.player(seat).energy += count
        return self.note(f"seat {seat} exhausts {count} rune(s) for {count} Energy")

    def recycle_rune_for_power(self, seat, oid):
        """Recycle a rune from the board for Power of its domain (164.2.b)."""
        rune = self.rune(oid)
        if rune.controller != seat:
            raise RulesError(f"rune {oid} is not controlled by seat {seat}")
        self.runes.remove(rune)
        self.player(seat).rune_deck.append(rune.name)
        domain = rune.domain or "Universal"
        self.add_power(seat, domain)
        return self.note(f"seat {seat} recycles {rune.name} [{oid}] for 1 {domain} Power")

    def cost_of(self, name):
        """The printed cost, and whether its Power split is determined.

        The card data carries a Power *count* and the card's domain list, not one
        domain per symbol. For a single-domain card that is exact. For a card
        with two domains and one Power symbol the printed symbol's domain is not
        recoverable, so the requirement is widened to "any of the card's
        domains" — permissive rather than strict, because a table that refuses a
        legal play is worse than one that allows an illegal one and says so.
        """
        energy = cards.energy_cost(name) or 0
        power = cards.power_cost(name) or 0
        domains = cards.domains(name)
        exact = power == 0 or len(domains) <= 1
        return {"energy": energy, "power": power, "domains": domains, "exact": exact}

    def can_pay(self, seat, name):
        """Is the printed cost payable from the pool plus readied runes?"""
        cost = self.cost_of(name)
        p = self.player(seat)
        mine = [r for r in self.runes if r.controller == seat]
        readied = [r for r in mine if not r.exhausted]
        usable_power = sum(
            n for d, n in p.power.items()
            if not cost["domains"] or d in cost["domains"] or d == "Universal"
        )
        power_short = max(cost["power"] - usable_power, 0)

        # 164.2.b's Power ability costs "Recycle this", not "[E]" — so an
        # EXHAUSTED rune can still be recycled for Power. Requiring it to be
        # readied refused payments the rules allow, which for a table is the
        # failure that stops it being used.
        def matching(runes):
            return [r for r in runes
                    if not cost["domains"] or r.domain in cost["domains"]]

        spent_runes = matching([r for r in mine if r.exhausted])
        from_exhausted = min(power_short, len(spent_runes))
        from_readied = power_short - from_exhausted
        if from_readied > len(matching(readied)):
            return False, (
                f"needs {cost['power']} Power of "
                f"{'/'.join(cost['domains']) or 'any domain'}"
            )
        # Only a READIED rune spent on Power costs you Energy; an exhausted one
        # had none left to give.
        energy_capacity = p.energy + len(readied) - from_readied
        if cost["energy"] > energy_capacity:
            return False, f"needs {cost['energy']} Energy, can raise {max(energy_capacity, 0)}"
        return True, ""

    def pay(self, seat, name, power_domains=None):
        """Pay a card's printed cost, exhausting and recycling runes to do it.

        Returns the runes spent. This is the bookkeeping most easily got wrong by
        hand — which rune paid for what, and how much of the pool is left.
        """
        ok, why = self.can_pay(seat, name)
        if not ok:
            raise RulesError(f"seat {seat} cannot pay for {name}: {why}")
        cost = self.cost_of(name)
        p = self.player(seat)
        spent = []

        for _ in range(cost["power"]):
            wanted = list(power_domains or cost["domains"])
            pooled = next(
                (d for d in p.power if p.power[d] > 0 and (not wanted or d in wanted or d == "Universal")),
                None,
            )
            if pooled:
                p.power[pooled] -= 1
                if not p.power[pooled]:
                    del p.power[pooled]
                continue
            # Spend an already-exhausted rune first: it has no Energy left to
            # give, so recycling it costs the turn nothing else.
            def usable(exhausted):
                return [r for r in self.runes
                        if r.controller == seat and r.exhausted is exhausted
                        and (not wanted or r.domain in wanted)]
            rune = next(iter(usable(True) + usable(False)), None)
            if rune is None:
                raise RulesError(f"seat {seat} has no rune to produce {'/'.join(wanted)} Power")
            self.recycle_rune_for_power(seat, rune.id)
            domain = rune.domain or "Universal"
            p.power[domain] -= 1
            if not p.power[domain]:
                del p.power[domain]
            spent.append(rune.name)

        short = cost["energy"] - p.energy
        if short > 0:
            self.tap_for_energy(seat, short)
        p.energy -= cost["energy"]
        self.note(
            f"seat {seat} pays {cost['energy']}E"
            + (f" + {cost['power']}P" if cost["power"] else "")
            + f" for {name}"
            + ("" if cost["exact"] else "  [power domain split not in the card data]")
        )
        return spent

    # -- movement (445) and contesting (190.3) ---------------------------

    def move(self, oid, destination):
        """Move a permanent. The Standard Move's exhaust cost is not charged here.

        Rule 144.2 makes exhausting the unit the cost of a Standard Move, but a
        spell or ability can move a unit without it — so the caller says which
        happened by exhausting or not.
        """
        perm = self.permanent(oid)
        self._require_location(destination)
        origin = perm.location
        if origin == destination:
            raise RulesError(f"{perm.name} is already at {self.where(destination)}")
        perm.location = destination
        self.note(f"{perm.name} [{oid}] moves {self.where(origin)} → {self.where(destination)}")
        if destination.startswith(BATTLEFIELD):
            self._apply_contested(perm)
        return perm

    def standard_move(self, oid, destination):
        """A unit's inherent Standard Move: exhaust, then move (144)."""
        perm = self.permanent(oid)
        if not perm.is_unit:
            raise RulesError(f"{perm.name} is not a unit — only units have a Standard Move (144)")
        if self.phase != MAIN:
            raise RulesError("a Standard Move can only be made during the Main Phase (144.1.a)")
        if perm.exhausted:
            raise RulesError(f"{perm.name} is exhausted and cannot pay its move cost (144.2)")
        # 144.4: base↔battlefield only, unless the unit has Ganking (810).
        origin_kind = perm.location.split(":")[0]
        dest_kind = destination.split(":")[0]
        if origin_kind == BATTLEFIELD and dest_kind == BATTLEFIELD:
            raise RulesError(
                f"{perm.name} would move battlefield→battlefield, which the Standard Move "
                "does not allow without Ganking (144.4.c) — use `move` if it has it"
            )
        self.exhaust(oid)
        return self.move(oid, destination)

    def recall(self, oid):
        """Return a permanent to its controller's base (454). Not a Move."""
        perm = self.permanent(oid)
        perm.location = f"{BASE}:{perm.controller}"
        return self.note(f"{perm.name} [{oid}] is recalled to base")

    def _apply_contested(self, perm):
        # 190.3.a: Contested is applied by a UNIT becoming present. Gear moving
        # to a battlefield does not contest it.
        if not perm.is_unit:
            return
        bf = self.battlefield(perm.location.split(":")[1])
        if bf.controller != perm.controller and not bf.contested:
            bf.contested = True
            bf.contested_by = perm.controller
            self.note(f"{bf.name} becomes CONTESTED by seat {perm.controller} (190.3.a.1)")

    # -- phases (314-317) ------------------------------------------------

    def begin_turn(self, seat=None):
        """Run Awaken, Beginning, Channel and Draw, ending in the Main Phase.

        Every step here is mandatory and automatic. Doing them by hand is where a
        game silently drifts: a missed Hold is a point that never existed, and a
        missed ready is a unit that could not have moved.
        """
        if self.winner is not None:
            raise RulesError(f"the game is over — seat {self.winner} has won")
        # 317.3 hands the turn over from the Ending Phase. Starting a turn from
        # the middle of another one skipped end-of-turn healing, expiry and pool
        # emptying — and the log then read as if they had happened.
        if self.setup_done and self.phase not in (None, ENDING):
            raise RulesError(
                f"turn {self.turn} is still in its {self.phase} phase — `endturn` "
                "first, or the healing, expiry and pool emptying it does never happen (317)"
            )
        if seat is not None:
            self.turn_player = seat
        self.turn += 1
        seat = self.turn_player

        # 315.1 Awaken — ready everything the turn player controls.
        self.phase = AWAKEN
        readied = [o for o in self.permanents + self.runes
                   if o.controller == seat and o.exhausted]
        for obj in readied:
            obj.exhausted = False
        self.note(f"— turn {self.turn}, seat {seat} — awaken: readied {len(readied)} object(s)")

        # 315.2.b Scoring Step — the turn player Holds every battlefield they control.
        self.phase = BEGINNING
        for bf in self.battlefields:
            bf.scored_by = set()
        for bf in self.battlefields:
            if bf.controller == seat:
                self.score(seat, bf.index, method="Hold")
        if self.winner is not None:
            # 196: when a player wins, the game ends — it does not finish the
            # phase. Channelling and drawing past the win leaves a final state
            # that never legally existed.
            self.note("the game ended during the Scoring Step; no further steps run")
            return self.phase

        # 315.3 Channel — 2 runes, plus one for the player going second on their
        # first turn of the game (485.7).
        self.phase = CHANNEL
        n = self.mode["channel_per_turn"]
        if seat != self.first_player and not self.second_player_channel_bonus_used:
            n += 1
            self.second_player_channel_bonus_used = True
            self.note("seat going second channels an extra rune this turn (485.7)")
        self.channel(seat, n)

        # 315.4 Draw.
        self.phase = DRAW
        self.draw(seat, 1, reason="draw phase")

        # 316.3 Main Phase begins by emptying every rune pool.
        self.phase = MAIN
        for p in self.players:
            self.empty_pool(p.seat)
        self.check_victory()
        return self.phase

    def end_turn(self):
        """Run the Ending Phase and hand the turn over (317)."""
        seat = self.turn_player
        self.phase = ENDING
        # 317.2.b Heal all units.
        healed = [p for p in self.permanents if p.is_unit and p.damage]
        for perm in healed:
            perm.damage = 0
        if healed:
            self.note(f"end of turn: healed {len(healed)} unit(s)")
        # 317.2.c "this turn" effects expire — the engine tracks none, so it says
        # so rather than implying there were none to expire.
        # 317.2.e Rune pools empty.
        for p in self.players:
            self.empty_pool(p.seat)
        self.cleanup()
        self.turn_player = self.opponent(seat)
        self.note(f"turn passes to seat {self.turn_player}")
        return self.turn_player

    def cleanup(self):
        """A Cleanup, in the order rule 323 lists its tasks."""
        # 323.1 is the victory check; it runs again at the end, once the board
        # has settled, because killing a unit can lose someone a battlefield.
        self.check_victory()

        # 323.5 (3b): every unit with lethal damage marked on it is killed.
        # Nothing did this outside combat, so a unit damaged by a spell simply
        # sat there until the Ending Phase healed it.
        for perm in list(self.permanents):
            if perm.is_unit and perm.damage > 0 and perm.damage >= perm.might:
                self.to_trash(perm.id, reason="lethal damage marked (323.5)")

        # 323.7 (5): anything resting where it does not belong goes home. Two of
        # the rule's clauses can bite here — unattached non-Unit Gear left at a
        # battlefield, and ANY permanent in a base that is not its controller's.
        # Without this a unit walked into the opponent's base stays there for the
        # rest of the game, which reads on the board as a presence it never has.
        # The rule's two Rune clauses are vacuous in this model: a Rune has no
        # location (161.1.a keeps it in its controller's base by construction),
        # so no rune can be at a battlefield or in a foreign base to recall.
        for perm in list(self.permanents):
            where, _, _idx = perm.location.partition(":")
            if where == BASE and perm.location != f"{BASE}:{perm.controller}":
                self.note(f"{perm.name} [{perm.id}] is in another player's base (323.7)")
                self.recall(perm.id)
            elif where == BATTLEFIELD and not perm.is_unit and perm.attached_to is None:
                self.note(
                    f"{perm.name} [{perm.id}] is unattached Gear at a battlefield (323.7)"
                )
                self.recall(perm.id)

        for bf in self.battlefields:
            here = self.units_at(bf.location)
            controllers = {u.controller for u in here}
            if bf.controller is not None and bf.controller not in controllers:
                # 190.4.c: no units there and the turn is open → control is lost.
                self.note(f"seat {bf.controller} loses control of {bf.name} (190.4.c)")
                bf.controller = None
            if not bf.contested or len(controllers) > 1:
                # Two players present is a staged combat, not something a
                # cleanup settles — control cannot change until the steps of
                # combat say so (190.4.b).
                continue
            # 323.11: Contested is removed from a battlefield with no units
            # controlled by the player who applied it and no combat ongoing.
            bf.contested = False
            bf.contested_by = None
            if len(controllers) == 1:
                # A unit moved onto a battlefield nobody was holding, and the
                # showdown closed with only that player present: they establish
                # control, which is a Conquer (466.5, 469.1). Leaving this to be
                # done by hand loses a point every time it is forgotten, and
                # moving in alone is the commonest way the game is scored at all.
                self.establish_control(next(iter(controllers)), bf.index)
        self.check_victory()

    # -- scoring (467-472) -----------------------------------------------

    def score(self, seat, index, method="Conquer"):
        """Score a battlefield for seat, if it has not already scored it (470)."""
        bf = self.battlefield(index)
        # 469.2: a Hold happens during the player's Beginning Phase. Awarding one
        # at any other time invents a point the rules never grant.
        if method == "Hold" and self.phase != BEGINNING:
            raise RulesError(
                f"a Hold is scored during the Beginning Phase, not {self.phase} (469.2)"
            )
        if seat in bf.scored_by:
            raise RulesError(
                f"seat {seat} already scored {bf.name} this turn — once per battlefield "
                "per turn (470)"
            )
        bf.scored_by.add(seat)
        p = self.player(seat)
        target = self.victory_target  # the Victory Score in force, not the mode's default

        # 471.1.b: a Conquer that would take a player to the Victory Score only
        # does so if they scored EVERY battlefield this turn; otherwise they draw.
        if method == "Conquer" and p.points >= target - 1:
            if all(seat in b.scored_by for b in self.battlefields):
                p.points += 1
                self.note(f"seat {seat} takes the FINAL POINT at {bf.name} (471.1.b.1)")
            else:
                self.note(
                    f"seat {seat} conquers {bf.name} but has not scored every battlefield "
                    "this turn — draws a card instead of the final point (471.1.b.1)"
                )
                self.draw(seat, 1, reason="final point denied")
                # 471.2: the Score happened, so the battlefield's Score
                # abilities trigger — only the point was withheld.
                self._note_score_trigger(bf)
                return p.points
        else:
            p.points += 1
            self.note(f"seat {seat} SCORES {bf.name} by {method} → {p.points} point(s)")

        self._note_score_trigger(bf)
        self.check_victory()
        return p.points

    def _note_score_trigger(self, bf):
        trigger = cards.text(bf.name) if cards.find(bf.name) else ""
        if trigger:
            self.note(f"  {bf.name} reads: {trigger}")

    def establish_control(self, seat, index):
        """Give seat control of a battlefield, Conquering it if not yet scored (466.5)."""
        bf = self.battlefield(index)
        was = bf.controller
        bf.contested = False
        bf.controller = seat
        self.note(f"seat {seat} establishes control of {bf.name}")
        if was != seat and seat not in bf.scored_by:
            self.score(seat, index, method="Conquer")
        return bf

    def set_target(self, value, reason=""):
        """Change the Victory Score, because a card said so."""
        old, self.victory_target = self.victory_target, int(value)
        return self.note(
            f"victory score {old} → {self.victory_target}" + (f" ({reason})" if reason else "")
        )

    def check_victory(self):
        """472: at a cleanup, the Victory Score with more points than any opponent wins."""
        if self.winner is not None:
            return self.winner
        target = self.victory_target
        eligible = [p for p in self.players if p.points >= target]
        if not eligible:
            return None
        best = max(eligible, key=lambda p: p.points)
        if all(best.points > o.points for o in self.players if o is not best):
            self.winner = best.seat
            self.note(f"seat {best.seat} WINS with {best.points} points (472)")
        return self.winner

    # -- combat (459-466) ------------------------------------------------

    def attacker_at(self, bf):
        """The Attacker at a battlefield: whoever's unit applied Contested (464.2.c.1).

        Assuming the turn player was wrong in both directions. A non-turn player
        can contest — a unit becoming present during a Showdown does it — and the
        designation decides which side a defender's "while I'm a defender" text
        applies to, and which side 466.1.a.2 recalls. Getting it backwards loses
        a battlefield its controller was holding.
        """
        if bf.contested_by is None:
            raise RulesError(
                f"{bf.name} has no recorded Attacker — nothing applied Contested to it, "
                "so there is no combat here to resolve (464.2.c.1)"
            )
        return bf.contested_by

    def staged_combats(self):
        """Battlefields where units of two opposing players are present (461)."""
        out = []
        for bf in self.battlefields:
            seats = {u.controller for u in self.units_at(bf.location)}
            if len(seats) == 2:
                out.append(bf)
        return out

    def assign_damage(self, attackers, defenders):
        """A legal damage assignment from one side onto the other (465.2.c).

        Lethal-first, and never more than the minimum lethal amount on a unit
        while another unit is still undamaged (465.2.c.3, 465.2.c.4). Returns
        {unit id: damage}. The order within the constraint is the assigning
        player's choice; this returns one legal ordering, which the caller may
        replace.
        """
        pool = sum(u.might for u in attackers)
        assignment = {}
        for target in defenders:
            if pool <= 0:
                break
            # 142.4.b: lethal is a NON-ZERO amount equalling or exceeding Might,
            # so the minimum lethal assignment for a 0-Might unit is 1, not 0.
            # Treating it as 0 assigned nothing, walked past a unit that could
            # still legally be assigned damage, and then dumped the excess on the
            # last defender — which 465.2.c.3 and 465.2.c.4 both forbid.
            already_lethal = target.damage > 0 and target.damage >= target.might
            need = 0 if already_lethal else max(target.might - target.damage, 1)
            give = min(pool, need)
            if give:
                assignment[target.id] = give
            pool -= give
        # 465.2.c.4: more than the minimum lethal is allowed only once no further
        # unit remains to be assigned damage — i.e. every defender already has
        # its full lethal, which is the only way `pool` survives the loop.
        if pool > 0 and defenders:
            last = defenders[-1]
            assignment[last.id] = assignment.get(last.id, 0) + pool
        return assignment

    def combat_preview(self, index):
        """What a combat would do, without doing it.

        Combat is the one moment where forgetting a card's text changes the
        result irreversibly — a unit reading "[Shield] (+1 Might while I'm a
        defender)" survives a hit that otherwise kills it, and once it is in the
        trash the game has already gone wrong. So the text of every unit
        involved is put in front of the reader before any damage is assigned,
        along with the assignment that would be made.

        Nothing here is applied. Buffs and modifiers are the reader's to add.
        """
        bf = self.battlefield(index)
        attacker_seat = self.attacker_at(bf)
        defender_seat = self.opponent(attacker_seat)
        attackers = self.units_at(bf.location, attacker_seat)
        defenders = self.units_at(bf.location, defender_seat)

        def describe(units, role):
            return [
                {
                    "id": u.id,
                    "name": u.name,
                    "might": u.might,
                    "buffs": u.buffs,
                    "damage": u.damage,
                    "role": role,
                    "text": cards.text(u.name) if cards.find(u.name) else "",
                }
                for u in units
            ]

        return {
            "battlefield": bf.name,
            "staged": bool(attackers and defenders),
            "attacker_seat": attacker_seat,
            "defender_seat": defender_seat,
            "attacker_might": sum(u.might for u in attackers),
            "defender_might": sum(u.might for u in defenders),
            "units": describe(attackers, "attacker") + describe(defenders, "defender"),
            "onto_defenders": self.assign_damage(attackers, defenders),
            "onto_attackers": self.assign_damage(defenders, attackers),
        }

    def resolve_combat(self, index, attacker_assignment=None, defender_assignment=None):
        """Run the Combat Damage and Resolution steps at a battlefield.

        The Combat Showdown Step (464) is not run here — that is a window in
        which players act, and this table does not act. Call this once both
        sides have finished acting.
        """
        bf = self.battlefield(index)
        seats = {u.controller for u in self.units_at(bf.location)}
        if len(seats) != 2:
            raise RulesError(f"no combat staged at {bf.name} — needs units from two players (461)")

        attacker_seat = self.attacker_at(bf)
        defender_seat = self.opponent(attacker_seat)
        attackers = self.units_at(bf.location, attacker_seat)
        defenders = self.units_at(bf.location, defender_seat)

        a_might = sum(u.might for u in attackers)
        d_might = sum(u.might for u in defenders)
        self.note(
            f"combat at {bf.name}: seat {attacker_seat} {a_might} Might vs "
            f"seat {defender_seat} {d_might} Might"
        )
        # The Might used here is what is on the table now. Any unit text that
        # would change it had to be applied first, so it is recorded alongside
        # the numbers — a log that shows both is auditable after the fact.
        for unit in attackers + defenders:
            if cards.find(unit.name) and cards.text(unit.name).strip():
                self.note(f"  [{unit.id}] {unit.name} ({unit.might}M) reads: {cards.text(unit.name)}")

        # 465.2.c: attacker assigns first, but damage is DEALT simultaneously,
        # so both assignments are computed before either is applied.
        # `or` was wrong here: an empty dict is falsy, so an explicit "no damage
        # is dealt" assignment — a Prevent effect (437), the plain way both sides
        # survive a combat — was silently replaced by the computed damage, and
        # the 466.1.a.2 recall branch became unreachable.
        onto_defenders = (
            self.assign_damage(attackers, defenders)
            if attacker_assignment is None else dict(attacker_assignment)
        )
        onto_attackers = (
            self.assign_damage(defenders, attackers)
            if defender_assignment is None else dict(defender_assignment)
        )

        for oid, amount in list(onto_defenders.items()) + list(onto_attackers.items()):
            if amount:
                perm = self.permanent(oid)
                perm.damage += amount
                self.note(f"  {perm.name} [{oid}] takes {amount} damage ({perm.damage}/{perm.might})")

        # Lethal damage kills (428), and lethal is NON-ZERO damage equalling or
        # exceeding Might (465.2.c.2) — so a 0-Might unit that was assigned
        # nothing survives, where a plain `damage >= might` kills it.
        dead = [u for u in attackers + defenders if u.damage > 0 and u.damage >= u.might]
        for unit in dead:
            self.to_trash(unit.id, reason="lethal combat damage")

        return self._combat_resolution(bf, attacker_seat, defender_seat)

    def _combat_resolution(self, bf, attacker_seat, defender_seat):
        """466: heal, recall repelled attackers, then decide control."""
        for perm in self.permanents:
            if perm.is_unit:
                perm.damage = 0  # 466.1.a.1 heal all units

        attackers = self.units_at(bf.location, attacker_seat)
        defenders = self.units_at(bf.location, defender_seat)

        # 466.1.a.2: attackers still present when defenders remain are recalled.
        repelled = bool(attackers and defenders)
        if repelled:
            for unit in list(attackers):
                self.recall(unit.id)
            self.note(f"attackers repelled at {bf.name} — no result (466.3.d)")

        bf.contested = False
        bf.contested_by = None
        remaining = self.units_at(bf.location)
        if not remaining:
            if bf.controller is not None:
                self.note(f"{bf.name} becomes uncontrolled (466.5.b)")
                bf.controller = None
            # 466.3.d calls this No Result: neither side was the only one left.
            return {"result": "no result", "battlefield": bf.name, "reason": "both sides destroyed"}

        # 466.5 runs whether or not the attackers were repelled: with no Showdown
        # or Combat still staged, whoever has units here establishes control, and
        # that is a Conquer if they had not scored it this turn. Returning early
        # on a repel meant a defender who had just held off an attack — and who
        # may not have controlled the battlefield before it — never took it.
        winner = remaining[0].controller
        self.establish_control(winner, bf.index)
        result = "attackers repelled" if repelled else "control established"
        return {"result": result, "battlefield": bf.name, "winner": winner}

    # -- serialisation ---------------------------------------------------

    def as_dict(self):
        return {
            "seed": self.seed,
            # The seed alone does not reproduce a game: every command reloads the
            # table, and a fresh Random(seed) starts at position 0, so the next
            # shuffle or draw repeats numbers the game has already used. Same
            # seed, different game, depending on how many processes touched it —
            # which makes "replay it with the same seed" untrue exactly when it
            # matters, comparing two decks over the same shuffles.
            "rng_state": _jsonable_rng(self.rng.getstate()),
            "seat_rng_state": [_jsonable_rng(r.getstate()) for r in self.seat_rng],
            "turn": self.turn,
            "phase": self.phase,
            "turn_player": self.turn_player,
            "first_player": self.first_player,
            "second_player_channel_bonus_used": self.second_player_channel_bonus_used,
            "winner": self.winner,
            "victory_target": self.victory_target,
            "setup_done": self.setup_done,
            "next_id": self._next_id,
            "players": [p.as_dict() for p in self.players],
            "battlefields": [b.as_dict() for b in self.battlefields],
            "permanents": [p.as_dict() for p in self.permanents],
            "runes": [r.as_dict() for r in self.runes],
            "chain": list(self.chain),
            "text_shown": sorted(self.text_shown),
            "log": list(self.log),
        }

    def restore(self, snapshot):
        """Roll this table back to a snapshot taken by `as_dict`.

        Restores in place rather than returning a new object, because the caller
        is holding this instance and a replacement would not reach it. The board
        is rebuilt though, so a `Permanent` or `Rune` reference taken before a
        rollback is stale — re-fetch by id.
        """
        other = Table.from_dict(snapshot, [p.deck for p in self.players])
        self.rng.setstate(other.rng.getstate())
        for mine, theirs in zip(self.seat_rng, other.seat_rng):
            mine.setstate(theirs.getstate())
        for field in ("turn", "phase", "turn_player", "first_player", "winner",
                      "victory_target", "second_player_channel_bonus_used",
                      "setup_done", "_next_id", "chain", "log", "text_shown",
                      "permanents", "runes", "battlefields"):
            setattr(self, field, getattr(other, field))
        for mine, theirs in zip(self.players, other.players):
            for field in ("champion_zone", "hand", "main_deck", "rune_deck",
                          "trash", "banished", "points", "energy", "power"):
                setattr(mine, field, getattr(theirs, field))
        return self

    @classmethod
    def from_dict(cls, raw, decks):
        t = cls(decks, raw["seed"], first=raw.get("first_player"))
        t.turn = raw["turn"]
        t.phase = raw["phase"]
        t.turn_player = raw["turn_player"]
        t.second_player_channel_bonus_used = raw.get("second_player_channel_bonus_used", False)
        t.winner = raw.get("winner")
        t.victory_target = raw.get("victory_target", t.mode["victory_score"])
        t.setup_done = raw.get("setup_done", False)
        t._next_id = raw.get("next_id", 1)
        t.chain = list(raw.get("chain", []))
        if raw.get("rng_state"):
            t.rng.setstate(_rng_from_json(raw["rng_state"]))
        for i, state in enumerate(raw.get("seat_rng_state") or []):
            t.seat_rng[i].setstate(_rng_from_json(state))
        t.text_shown = set(raw.get("text_shown", []))
        t.log = list(raw.get("log", []))
        for p, saved in zip(t.players, raw["players"]):
            for field in ("champion_zone", "hand", "main_deck", "rune_deck", "trash", "banished"):
                setattr(p, field, list(saved[field]))
            p.points = saved["points"]
            p.energy = saved["energy"]
            p.power = dict(saved["power"])
        t.battlefields = []
        for saved in raw["battlefields"]:
            bf = Battlefield(saved["index"], saved["name"], saved["provided_by"])
            bf.controller = saved["controller"]
            bf.contested = saved["contested"]
            bf.contested_by = saved.get("contested_by")
            bf.scored_by = set(saved["scored_by"])
            t.battlefields.append(bf)
        t.permanents = []
        for saved in raw["permanents"]:
            perm = Permanent(saved["id"], saved["name"], saved["controller"], saved["location"])
            perm.owner = saved["owner"]
            perm.exhausted = saved["exhausted"]
            perm.damage = saved["damage"]
            perm.buffs = saved["buffs"]
            perm.attached_to = saved["attached_to"]
            perm.note = saved.get("note", "")
            t.permanents.append(perm)
        t.runes = [Rune(s["id"], s["name"], s["controller"], s["exhausted"]) for s in raw["runes"]]

        # Derive the id counter from the board instead of trusting the file.
        # A saved game is internally consistent — every id on it is unique — but
        # that says nothing about what the LOADER then mints: a save written
        # without `next_id`, or with a stale one, left the counter behind the
        # board and the next `_oid` handed out an id an object already had. Two
        # permanents then answered to the same id and `permanent()` returned
        # whichever came first, so a kill or a move hit the wrong unit silently.
        t._next_id = max([t._next_id] + [_id_number(o.id) + 1 for o in t.permanents + t.runes])
        return t
