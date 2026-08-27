"""Regression harness for the table.

Every check here exists because the thing it checks is something a game silently
gets wrong when done by hand: a missed Hold is a point that never happened, a
mis-assigned combat is a unit that should have died, a re-scored battlefield is
a point scored twice. The whole reason to have an engine is that these are
decided by code, so they have to be decided correctly.

    python3 deck_cli.py selftest

Exit 0 = the table can be trusted to hold a game.
"""
import copy
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import cards
import deckfile
import table
from table import RulesError

FAILS = []
RAN = [0]


def check(name, ok, detail=""):
    RAN[0] += 1
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}{'  — ' + detail if detail else ''}")
    if not ok:
        FAILS.append(name)
    return ok


def raises(fn, fragment=""):
    try:
        fn()
    except RulesError as err:
        return fragment.lower() in str(err).lower()
    except Exception:
        return False
    return False


# -- fixtures ------------------------------------------------------------

def _lookup_message(name):
    try:
        cards.require(name)
    except KeyError as err:
        return str(err)
    return ""


def _ambiguity_message_names_options():
    try:
        cards.require("Master Yi")
    except KeyError as err:
        return "ambiguous" in str(err) and "Wuju Bladesman" in str(err)
    return False


def two_decks():
    """Two real gauntlet decks, so the table is exercised against real lists."""
    return (
        deckfile.resolve("irelia-blade-dancer-irelia-2025-12-17"),
        deckfile.resolve("master-yi-wuju-bladesman-shanghai-national-open-2nd-place"),
    )


def fresh(seed=7, first=0):
    a, b = two_decks()
    return table.Table([a, b], seed=seed, first=first).setup()


def _next_random(t):
    """The next number from t's shared generator, from a copy so t is untouched."""
    return _next_random_of(t.rng)


def _next_random_of(gen):
    import random as _r
    clone = _r.Random()
    clone.setstate(gen.getstate())
    return clone.random()


def _attacker_or_none(t, bf):
    """The Attacker, or None when the table cannot say — a failure, not a crash."""
    try:
        return t.attacker_at(bf)
    except RulesError:
        return None


def _resolve(t, index, **kw):
    """Resolve a combat, turning a refusal into a reportable result.

    A check that dies takes the whole suite with it and reports nothing — which
    is indistinguishable from the suite never having run. Every combat check
    goes through here so a refusal shows up as a named failure instead.
    """
    try:
        return t.resolve_combat(index, **kw)
    except RulesError as err:
        return {"result": f"<refused> {err}", "battlefield": None}


def _roles_or_empty(t, index):
    try:
        return {u["id"]: u["role"] for u in t.combat_preview(index)["units"]}
    except RulesError:
        return {}


def stub_unit(t, seat, name, location, exhausted=False):
    """Put a unit somewhere, through the same arrival path real play uses.

    It used to append straight to `t.permanents`, which skipped `_apply_contested`
    — so every combat test ran against a battlefield that nothing had contested,
    and none of them exercised the Attacker designation at all.
    """
    perm = table.Permanent(t._oid("u"), name, seat, location)
    perm.exhausted = exhausted
    t.permanents.append(perm)
    if location.startswith(table.BATTLEFIELD):
        t._apply_contested(perm)
    return perm


# -- card data -----------------------------------------------------------

def card_lookup():
    check(
        "a subtitled card resolves across the separator both sources use",
        cards.find("Master Yi, Wuju Bladesman") is not None
        and cards.find("Master Yi - Wuju Bladesman") is not None,
        "decklists write ', ', the card data writes ' - '",
    )
    check(
        "a name that could mean six different cards resolves to none of them",
        cards.find("Master Yi") is None and len(cards.candidates("Master Yi")) == 6,
        "picking one would shuffle a card into the deck the list never asked for",
    )
    check(
        "an ambiguous name is refused with the options named",
        _ambiguity_message_names_options(),
    )
    check(
        "a name that matches nothing at all returns nothing",
        cards.find("Definitely Not A Card") is None
        and cards.candidates("Definitely Not A Card") == [],
    )
    check(
        "an absent name is no card, not a crash",
        cards.find(None) is None and cards.find("") is None,
        "a deck with no Chosen Champion set is a legality error, not a traceback",
    )
    check(
        "colorless is domainless, not a seventh domain",
        cards.domains("The Dreaming Tree") == []
        and "Colorless" in cards.printed_domains("The Dreaming Tree"),
        "reading it literally makes 69 cards illegal in every deck",
    )


# -- deck construction (103) ---------------------------------------------

def deck_legality():
    decks = [deckfile.load(p) for p in deckfile.available()]
    results = [(d, deckfile.check(d)) for d in decks]
    legal = [d for d, r in results if r.legal]
    # Every shipped deck must be playable. Tolerating unresolved champions meant
    # 5 of 24 shipped unusable and nothing said so.
    illegal = [(d.name, r.errors[:1]) for d, r in results if not r.legal]
    check("every deck that ships is legal and playable",
          not illegal,
          f"{len(legal)}/{len(results)} legal"
          + ("" if not illegal else f" — {illegal[0][0]}: {illegal[0][1]}"))

    d = copy.deepcopy(legal[0])
    d.main = [(n, 4 if i == 0 else q) for i, (n, q) in enumerate(d.main)]
    check("a 4th copy of a card is rejected (103.2.b)",
          any("3-copy" in e for e in deckfile.check(d).errors))

    # Drop a COPY, not an entry. Slicing entries assumed the fixture deck spread
    # its runes over two names; a deck running a single "12x Body Rune" entry
    # kept all 12 after the slice, so this check silently stopped testing
    # anything the moment such a deck sorted first.
    d = copy.deepcopy(legal[0])
    d.runes = [(d.runes[0][0], d.runes[0][1] - 1)] + d.runes[1:]
    check("a rune deck that is not exactly 12 is rejected (103.3.a)",
          any("Rune Deck has" in e for e in deckfile.check(d).errors))

    d = copy.deepcopy(legal[0])
    d.chosen_champion = None
    # Cite the rule, not merely the field name: with the 103.2.a.1 branch removed
    # the code still errors — "chosen_champion None is not in the card pool" —
    # so matching on the field name passed while the rule was gone.
    check("a deck with no Chosen Champion is rejected (103.2.a.1)",
          any("103.2.a.1" in e for e in deckfile.check(d).errors),
          "; ".join(deckfile.check(d).errors)[:80])

    d = copy.deepcopy(legal[0])
    d.battlefields = [(d.battlefields[0][0], 3)]
    check("duplicate battlefield names are rejected (103.4.c)",
          any("distinct names" in e for e in deckfile.check(d).errors))

    # 103.2.a.2 binds by CHAMPION tag. A legend also carries traits and regions —
    # a Kennen legend is tagged ['Yordle', 'Kennen'] — so matching on any shared
    # tag let Fizz, also a Yordle, pass as its Chosen Champion.
    ct = cards.champion_tags()
    check("champion tags are told apart from traits and regions (103.2.a.2)",
          "Yordle" not in ct and "Kennen" in ct,
          f"{len(ct)} champion tags derived")
    check("every legend in the pool has a derivable champion tag",
          not [v for v in cards.pool().values()
               if v["stats"]["type"] == cards.LEGEND
               and not (set(v["stats"].get("tags") or []) & ct)],
          "a legend with none would accept any champion at all")
    check("a champion sharing only a trait is not a legal Chosen Champion",
          not (cards.champion_tags_of("Yordle, Kennen - Heart of the Tempest")
               & cards.champion_tags_of("Fizz - Trickster")))
    # Through the legality check itself, not just the helper: a Kennen legend
    # with Fizz — same Yordle trait, different champion — must be refused.
    wrong = deckfile.Deck({
        "name": "kennen legend with a fizz champion",
        "legend": "Yordle, Kennen - Heart of the Tempest",
        "chosen_champion": "Fizz - Trickster",
        "main": [{"name": "Fizz - Trickster", "qty": 3}],
        "runes": [], "battlefields": [],
    })
    check("a deck whose champion shares only a trait is rejected (103.2.a.2)",
          any("champion tag" in e for e in deckfile.check(wrong).errors),
          "both are Yordles; only Kennen is the legend's CHAMPION tag")

    # A deck naming a card ambiguously is a different problem from one naming a
    # card that does not exist, and the message has to say which — "not in the
    # card pool" sent the reader looking for a data problem that is not there.
    amb = copy.deepcopy(legal[0])
    amb.main = [("Master Yi", 1)] + amb.main[1:]
    amb_errors = deckfile.check(amb).errors
    check("a deck naming an ambiguous card says so, not 'not in the card pool'",
          any("ambiguous" in e for e in amb_errors)
          and not any("not in the card pool" in e and "Master Yi" in e for e in amb_errors),
          "; ".join(amb_errors)[:90])

    check("format legality is reported as unchecked, not as a pass",
          any("103.2.e" in u for u in deckfile.check(legal[0]).unchecked))
    check("the Domain exception is reported as unchecked too (103.1.b.5)",
          any("103.1.b.5" in u for u in deckfile.check(legal[0]).unchecked),
          "silence there reads as 'checked and fine'")

    # Every legality rule counts CARDS. Counting the deck's JSON entries let
    # three separate rules pass things they forbid.
    d = copy.deepcopy(legal[0])
    first = d.main[0][0]
    d.main = [(first, 3), (first, 3)] + d.main[1:]
    check("the copy limit counts a card across every entry naming it (103.2.b)",
          any("6x" in e and "3-copy" in e for e in deckfile.check(d).errors),
          "two entries of three is six copies, not two legal threes")

    d = copy.deepcopy(legal[0])
    bf = d.battlefields[0][0]
    d.battlefields = [(bf, 1), (bf, 1), (d.battlefields[1][0], 1)]
    check("the same battlefield listed twice is caught (103.4.c)",
          any("distinct names" in e for e in deckfile.check(d).errors))

    d = copy.deepcopy(legal[0])
    cc = d.chosen_champion
    d.main = [(cc, 1), (cc, 2)] + [m for m in d.main if m[0] != cc]
    check("exactly one Chosen Champion copy leaves the deck, however it is listed (112)",
          sum(1 for n in d.main_cards() if n == cc) == 2,
          "removing one per matching entry silently deleted a card from the deck")

    d = legal[0]
    check(
        "the Chosen Champion is not shuffled into the Main Deck (112)",
        sum(1 for n in d.main_cards() if n == d.chosen_champion)
        == sum(q for n, q in d.main if n == d.chosen_champion) - 1,
        "it starts in the Champion Zone, so it can never be drawn",
    )


# -- setup and determinism -----------------------------------------------

def setup_rules():
    t = fresh()
    check("both players open on 4 cards (116)",
          all(len(p.hand) == 4 for p in t.players))
    check("each player's Chosen Champion starts in the Champion Zone (112)",
          all(len(p.champion_zone) == 1 for p in t.players))
    check("exactly 2 battlefields are in play, one from each deck (485.4)",
          len(t.battlefields) == 2
          and {b.provided_by for b in t.battlefields} == {0, 1})

    a, b = fresh(seed=99), fresh(seed=99)
    check("the same seed replays the same game exactly",
          [p.hand for p in a.players] == [p.hand for p in b.players]
          and [bf.name for bf in a.battlefields] == [bf.name for bf in b.battlefields])
    firsts = {table.Table(list(two_decks()), seed=771).setup().first_player for _ in range(6)}
    check("who goes first is decided by the seed, not the clock (115)",
          len(firsts) == 1,
          "six tables built at one seed all chose the same first player")

    c = fresh(seed=100)
    check("a different seed deals a different game",
          [p.hand for p in a.players] != [p.hand for p in c.players])

    # A seat's shuffle must not depend on what the OTHER seat brought. One shared
    # generator drew both shuffles from one stream, so the opponent's order was a
    # function of how many numbers your deck's shuffle consumed — accidental
    # pairing for equal-length decks, and silent UNpairing the moment the lists
    # differed in size.
    # The sizes have to DIFFER for this to test anything: shuffling a list of n
    # consumes n-1 draws whatever it contains, so two 39-card decks pair even on
    # a shared stream. Every gauntlet deck is 39, which is why the obvious
    # version of this check passed against the bug it was named for.
    opp = deckfile.resolve("master-yi-wuju-bladesman-shanghai-national-open-2nd-place-a6810f")
    base = deckfile.resolve("irelia-blade-dancer-irelia-2025-12-17-43d7e2")
    hands, sizes = [], []
    for pad in (0, 6):
        deck = copy.deepcopy(base)
        if pad:
            deck.main = deck.main + [("Called Shot", pad)]
        t = table.Table([deck, opp], seed=4242, first=0).setup()
        hands.append(tuple(t.player(1).hand))
        sizes.append(len(deck.main_cards()))
    check("a seat's shuffle does not depend on the opposing deck",
          len(set(hands)) == 1,
          f"decks of {sizes[0]} and {sizes[1]} shuffled cards deal the same opponent hand")
    other = table.Table([deckfile.resolve("irelia-blade-dancer-irelia-2025-12-17-43d7e2"), opp],
                        seed=4243, first=0).setup()
    check("a different seed still deals the opponent a different hand",
          tuple(other.player(1).hand) != hands[0],
          "pairing must come from reusing a seed, never from being unable to vary")

    # A game is played across many commands, each of which reloads the table.
    # Continuing the SAME stream is what makes a seed reproduce a game.
    t = fresh(seed=5, first=0)
    t.mulligan(0, set_aside=[t.player(0).hand[0]])
    t.begin_turn(0)
    direct = list(t.player(0).hand)
    u = fresh(seed=5, first=0)
    u.mulligan(0, set_aside=[u.player(0).hand[0]])
    reloaded = table.Table.from_dict(json.loads(json.dumps(u.as_dict())), list(two_decks()))
    reloaded.begin_turn(0)
    check("a seeded game survives being saved and reloaded mid-play",
          reloaded.player(0).hand == direct,
          "the generator continues where it left off, rather than restarting")

    t = fresh()
    aside = t.player(0).hand[:2]
    kept = [c for c in t.player(0).hand if c not in aside]
    t.mulligan(0, set_aside=aside)
    check("a mulligan redraws to the same hand size (117.2)",
          len(t.player(0).hand) == 4)
    check("the cards not set aside are still in hand",
          all(k in t.player(0).hand for k in kept))
    check("a mulligan sets aside at most two cards (117.1)",
          raises(lambda: fresh().mulligan(0, set_aside=fresh().player(0).hand[:3]),
                 "at most"))

    # 117.2 then 117.3: draw FIRST, recycle after. Shuffling the set-aside cards
    # back before redrawing let a card you had just thrown away come right back.
    #
    # Cutting the deck to a single known card is what makes this decisive: in the
    # right order the replacement can only be that card, and the set-aside one
    # ends up in the deck. In the wrong order the deck holds both at draw time
    # and which one is drawn is a coin flip, so it fails across seeds.
    came_back = []
    for seed in range(12):
        t = fresh(seed=seed)
        aside = [n for n in t.player(0).hand
                 if t.player(0).hand.count(n) == 1][:1]
        if not aside:
            continue
        filler = next(n for n in t.player(0).main_deck if n not in t.player(0).hand)
        t.player(0).main_deck = [filler]
        t.mulligan(0, set_aside=aside)
        if aside[0] in t.player(0).hand or filler not in t.player(0).hand:
            came_back.append(seed)
    check("a set-aside card cannot be redrawn by the same mulligan (117.2/117.3)",
          not came_back,
          f"it goes back to the deck only after the replacement is drawn"
          if not came_back else f"redrawn on seeds {came_back}")


# -- the turn (314-317) --------------------------------------------------

def turn_structure():
    t = fresh(first=0)
    t.begin_turn()
    check("the turn player channels 2 runes (315.3)", len(t.runes) == 2)
    check("the turn player draws for turn (315.4)", len(t.player(0).hand) == 5)
    check("play reaches the Main Phase", t.phase == table.MAIN)

    t.end_turn()
    t.begin_turn()
    check("the player going second channels 3 on their first turn (485.7)",
          len([r for r in t.runes if r.controller == 1]) == 3)
    t.end_turn()
    t.begin_turn()
    t.end_turn()
    t.begin_turn()
    check("the extra rune is granted once, not every turn",
          len([r for r in t.runes if r.controller == 1]) == 5,
          "3 on the first turn, 2 on the second")

    t = fresh(first=0)
    t.begin_turn()
    unit = stub_unit(t, 0, "Stellacorn Herder", "base:0", exhausted=True)
    t.runes[0].exhausted = True
    t.end_turn()
    t.begin_turn(seat=0)
    check("Awaken readies everything the turn player controls (315.1.b)",
          not unit.exhausted and not any(r.exhausted for r in t.runes if r.controller == 0))

    t = fresh(first=0)
    t.begin_turn()
    t.add_energy(0, 3)
    t.end_turn()
    check("unspent Energy is lost at end of turn (317.2.e)", t.player(0).energy == 0)

    # 317.3 hands the turn over from the Ending Phase. Starting one from the
    # middle of another skipped healing, expiry and pool emptying, and the log
    # then read as though they had happened.
    t = fresh(first=0)
    t.begin_turn()
    check("a turn cannot begin while another is still running (317)",
          raises(lambda: t.begin_turn(1), "endturn"))
    t.end_turn()
    t.begin_turn(1)
    check("and begins normally once the previous one ended", t.turn == 2)


# -- resources (163-168) -------------------------------------------------

def resources():
    t = fresh(first=0)
    t.begin_turn()
    t.tap_for_energy(0, 2)
    check("exhausting a rune adds 1 Energy (164.2.a)",
          t.player(0).energy == 2 and all(r.exhausted for r in t.runes if r.controller == 0))
    check("a rune cannot be exhausted twice",
          raises(lambda: t.tap_for_energy(0, 1), "readied rune"))

    t = fresh(first=0)
    t.begin_turn()
    rune = [r for r in t.runes if r.controller == 0][0]
    domain = rune.domain
    t.recycle_rune_for_power(0, rune.id)
    check("recycling a rune adds Power of its domain (164.2.b.1)",
          t.player(0).power.get(domain) == 1)
    check("a recycled rune returns to the Rune Deck, not the Main Deck (161.2.b)",
          rune.name in t.player(0).rune_deck and rune.name not in t.player(0).main_deck)

    # 316.3 empties EVERY player's pool entering the Main Phase, including the
    # player whose turn it is not. Routing this through end_turn proved nothing:
    # 317.2.e empties the pools too, so the check passed with 316.3 deleted.
    t = fresh(first=0)
    t.begin_turn()
    t.end_turn()
    t.add_energy(0, 5)
    t.add_energy(1, 5)
    t.begin_turn()
    check("the rune pool is emptied entering the Main Phase (316.3)",
          t.player(0).energy == 0 and t.player(1).energy == 0,
          "both players, not just the turn player")


def paying():
    t = fresh(first=0)
    t.begin_turn()
    # A cheap domainless-cost card the deck actually runs.
    name = next(
        (n for n in t.player(0).main_deck
         if (cards.energy_cost(n) or 0) <= 2 and not cards.power_cost(n)),
        None,
    )
    if name is None:
        return check("a payable card exists to test with", False)
    t.player(0).hand.append(name)
    ok, why = t.can_pay(0, name)
    check(f"a {cards.energy_cost(name)}-Energy card is payable from 2 runes", ok, why)
    t.pay(0, name)
    check("paying leaves the pool at zero", t.player(0).energy == 0)

    expensive = max(t.player(0).main_deck, key=lambda n: cards.energy_cost(n) or 0)
    if (cards.energy_cost(expensive) or 0) > 2:
        ok, why = t.can_pay(0, expensive)
        check("a cost beyond the runes available is refused, with the reason",
              not ok and "Energy" in why, why)

    check("an unpayable cost raises rather than going through",
          raises(lambda: t.pay(0, expensive), "cannot pay"))

    # 164.2.b's Power ability costs "Recycle this", not "[E]" — an exhausted
    # rune can still be recycled for Power. Requiring it readied refused
    # payments the rules allow.
    t = fresh(first=0)
    t.begin_turn()
    powered = next(
        (n for n in t.player(0).main_deck
         if (cards.power_cost(n) or 0) == 1
         and set(cards.domains(n)) & {r.domain for r in t.runes if r.controller == 0}),
        None,
    )
    if powered is None:
        check("a Power-costed card exists in this deck to test with", False)
    else:
        t.player(0).hand.append(powered)
        for r in [r for r in t.runes if r.controller == 0]:
            r.exhausted = True
        t.add_energy(0, cards.energy_cost(powered) or 0)
        ok, why = t.can_pay(0, powered)
        check("Power can be recycled from an EXHAUSTED rune (164.2.b)", ok,
              why or f"{powered}: exhausted runes still recycle for Power")
        t.pay(0, powered)
        check("paying that way actually recycles the rune",
              powered not in [r.name for r in t.runes])


# -- movement and contesting (144, 190.3) --------------------------------

def movement():
    t = fresh(first=0)
    t.begin_turn()
    unit = stub_unit(t, 0, "Stellacorn Herder", "base:0")
    t.standard_move(unit.id, "bf:0")
    check("a Standard Move exhausts the unit (144.2)", unit.exhausted)
    check("arriving at an uncontrolled battlefield contests it (190.3.a.1)",
          t.battlefield(0).contested)

    other = stub_unit(t, 0, "Stellacorn Herder", "bf:0")
    check("the Standard Move cannot go battlefield → battlefield without Ganking (144.4)",
          raises(lambda: t.standard_move(other.id, "bf:1"), "ganking"))

    exhausted = stub_unit(t, 0, "Stellacorn Herder", "base:0", exhausted=True)
    check("an exhausted unit cannot pay its own move cost",
          raises(lambda: t.standard_move(exhausted.id, "bf:0"), "exhausted"))

    t.phase = table.ENDING
    late = stub_unit(t, 0, "Stellacorn Herder", "base:0")
    check("a Standard Move outside the Main Phase is refused (144.1.a)",
          raises(lambda: t.standard_move(late.id, "bf:0"), "main phase"))


# -- combat (459-466) ----------------------------------------------------

def combat():
    t = fresh(first=0)
    t.begin_turn()
    # Two 4-Might attackers into one 4-Might and one 1-Might defender.
    a1 = stub_unit(t, 0, "Irelia, Fervent", "bf:0")
    a2 = stub_unit(t, 0, "Irelia, Fervent", "bf:0")
    d1 = stub_unit(t, 1, "Irelia, Fervent", "bf:0")
    d2 = stub_unit(t, 1, "Irelia, Fervent", "bf:0")
    assignment = t.assign_damage([a1, a2], [d1, d2])
    check("damage is assigned lethal-first, not spread (465.2.c.3)",
          assignment[d1.id] == d1.might and assignment.get(d2.id, 0) == 8 - d1.might,
          str(assignment))

    # 465.2.c.3 + 142.4.b: a 0-Might unit's minimum lethal is 1, not 0. Reading
    # it as 0 assigned it nothing, walked past a unit that could still legally be
    # assigned damage, and dumped the excess on the last defender instead — which
    # 465.2.c.4 forbids while any unit is still owed its lethal.
    t = fresh(first=0)
    t.begin_turn()
    hitter = stub_unit(t, 0, "Irelia, Fervent", "bf:0")      # 4 Might
    zero = stub_unit(t, 1, "Scuttle Crab", "bf:0")           # printed 0 Might
    other = stub_unit(t, 1, "Stalwart Poro", "bf:0")         # 2 Might
    a = t.assign_damage([hitter], [zero, other])
    check("a 0-Might unit is assigned its minimum lethal of 1, not skipped (142.4.b)",
          a.get(zero.id) == 1,
          f"assigned {a}")
    check("the excess is not dumped while a unit is still owed lethal (465.2.c.4)",
          a.get(other.id, 0) <= other.might + 1,
          f"assigned {a}")

    t = fresh(first=0)
    t.begin_turn()
    big = stub_unit(t, 0, "Irelia, Fervent", "bf:0")   # 4 Might
    small = stub_unit(t, 1, "Stellacorn Herder", "bf:0")
    a = t.assign_damage([big], [small])
    check("no more than minimum lethal is assigned while it is the only target (465.2.c.4)",
          a[small.id] == big.might,
          "excess has nowhere else to go, so it stays on the last unit")

    t = fresh(first=0)
    t.begin_turn()
    stub_unit(t, 0, "Irelia, Fervent", "bf:0")
    stub_unit(t, 1, "Irelia, Fervent", "bf:0")
    result = _resolve(t, 0)
    check("equal Might trades both units simultaneously (465.2.c.1.a)",
          t.units_at("bf:0") == [] and result["result"] == "no result",
          "466.3.d: neither side was the only one left, so it is No Result")

    # The attacker must SURVIVE for this to test a recall at all — an attacker
    # that dies satisfies "not standing at the battlefield" without any recall
    # happening, which is how the previous version of this check stayed green
    # with 466.1.a.2 deleted.
    #
    # Both sides surviving cannot happen on unmodified damage: each deals its
    # full summed Might, so the larger side always wipes the smaller. The branch
    # is reachable only once an effect changes the damage — Prevent (437) is the
    # plain case — which is what the explicit assignment arguments are for.
    t = fresh(first=0)
    t.begin_turn()
    attacker = stub_unit(t, 0, "Irelia, Fervent", "bf:0")
    defender = stub_unit(t, 1, "Irelia, Fervent", "bf:0")
    result = _resolve(t, 0, attacker_assignment={}, defender_assignment={})
    check("a repelled attacker is recalled to base, not left standing (466.1.a.2)",
          attacker in t.permanents and attacker.location == "base:0"
          and defender.location == "bf:0",
          f"damage prevented, so both survive and only a recall clears the "
          f"battlefield — {result['result']}")

    t = fresh(first=0)
    t.begin_turn()
    winner = stub_unit(t, 0, "Irelia, Fervent", "bf:0")
    stub_unit(t, 1, "Stellacorn Herder", "bf:0")
    before = t.player(0).points
    _resolve(t, 0)
    check("winning a combat establishes control and Conquers (466.5.d)",
          t.battlefield(0).controller == 0 and t.player(0).points == before + 1)
    check("units are healed after combat (466.1.a.1)", winner.damage == 0)

    # 465.2.c.2: lethal is NON-ZERO damage equalling or exceeding Might. A plain
    # `damage >= might` kills a 0-Might unit that was never assigned anything.
    t = fresh(first=0)
    t.begin_turn()
    zero = stub_unit(t, 1, "Stellacorn Herder", "bf:0")
    zero.buffs = -zero.base_might
    stub_unit(t, 0, "Stellacorn Herder", "bf:0").buffs = -3
    _resolve(t, 0)
    check("a 0-Might unit assigned no damage is not lethally damaged (465.2.c.2)",
          zero in t.permanents)

    # Forgetting a unit's text is the one mistake combat makes irreversible:
    # "Stalwart Poro" reads "[Shield] (+1 Might while I'm a defender)" and dies
    # to 3 damage at 2 Might, survives at 3.
    t = fresh(first=0)
    t.begin_turn()
    stub_unit(t, 0, "Stellacorn Herder", "bf:0")
    poro = stub_unit(t, 1, "Stalwart Poro", "bf:0")
    preview = t.combat_preview(0)
    check("the preview shows every involved unit's printed text",
          all("text" in u for u in preview["units"])
          and any("Shield" in u["text"] for u in preview["units"]))
    check("the preview changes nothing", poro in t.permanents and poro.damage == 0)
    check("the preview reports an assignment that is at least lethal",
          preview["onto_defenders"].get(poro.id) >= poro.might,
          "3 Might onto one 2-Might unit: the excess has nowhere else to go")
    # Lethal is damage EQUALLING or exceeding Might, so +1 does not save a
    # 2-Might unit from 3 damage — it takes +2 to change the outcome.
    poro.buffs += 2
    _resolve(t, 0)
    check("a Might change applied before combat changes who dies",
          poro in t.permanents,
          "at 4 Might the Poro survives the 3 damage that killed it at 2")
    check("combat logs the text of the units that fought, so it can be audited",
          any("reads:" in e["text"] and "Shield" in e["text"] for e in t.log))

    # 464.2.c.1: the Attacker is whoever's unit applied Contested, which need not
    # be the turn player. Assuming the turn player swapped the designations, so a
    # defender's "while I'm a defender" text was applied to the wrong side and
    # 466.1.a.2 recalled the wrong units.
    t = fresh(first=0)
    t.begin_turn()
    holder = stub_unit(t, 0, "Stalwart Poro", "bf:0")
    t.battlefield(0).controller = 0
    t.battlefield(0).contested = False
    t.battlefield(0).contested_by = None
    intruder = t.put_into_play(1, "Stalwart Poro", "bf:0", source="elsewhere")
    check("the Attacker is whoever applied Contested, not the turn player (464.2.c.1)",
          _attacker_or_none(t, t.battlefield(0)) == 1,
          "seat 0 is the turn player; seat 1 moved in and contested")
    roles = _roles_or_empty(t, 0)
    check("the preview labels the resident unit the defender",
          roles.get(holder.id) == "defender" and roles.get(intruder.id) == "attacker")

    # 466.5 runs even when the attackers were repelled: the defender is the only
    # player left there, so they establish control — and Conquer if they had not
    # already scored it. Returning early on a repel skipped that entirely.
    t = fresh(first=0)
    t.begin_turn()
    t.put_into_play(0, "Stalwart Poro", "bf:0", source="elsewhere")   # seat 0 contests an empty bf
    defender = stub_unit(t, 1, "Stalwart Poro", "bf:0")
    t.battlefield(0).controller = None
    before = t.player(1).points
    result = _resolve(t, 0, attacker_assignment={}, defender_assignment={})
    check("a repelled attack still leaves the defender establishing control (466.5)",
          result["result"] == "attackers repelled"
          and t.battlefield(0).controller == 1 and t.player(1).points == before + 1)

    # 323.5: a unit with lethal damage marked on it is killed at the next
    # cleanup. Nothing did that outside combat, so a unit damaged by a spell sat
    # there until the Ending Phase healed it.
    t = fresh(first=0)
    t.begin_turn()
    hurt = stub_unit(t, 0, "Stalwart Poro", "base:0")
    hurt.damage = hurt.might
    t.cleanup()
    check("a unit with lethal damage marked is killed at a cleanup (323.5)",
          hurt not in t.permanents)

    # 190.3.a: Contested is applied by a UNIT becoming present.
    t = fresh(first=0)
    t.begin_turn()
    gear = t.put_into_play(0, "Zhonya's Hourglass", "bf:0", source="elsewhere")
    check("gear arriving at a battlefield does not contest it (190.3.a)",
          not gear.is_unit and not t.battlefield(0).contested)


# -- scoring (467-472) ---------------------------------------------------

def scoring():
    t = fresh(first=0)
    t.begin_turn()
    t.battlefield(0).controller = 0
    t.score(0, 0, method="Conquer")
    check("scoring gains a point", t.player(0).points == 1)
    # 469.2: a Hold is scored during the Beginning Phase and nowhere else.
    check("a Hold outside the Beginning Phase is refused (469.2)",
          raises(lambda: t.score(0, 1, method="Hold"), "Beginning Phase"))
    check("a battlefield cannot be scored twice in a turn (470)",
          raises(lambda: t.score(0, 0), "already scored"))

    t = fresh(first=0)
    stub_unit(t, 0, "Irelia, Fervent", "bf:0")
    t.battlefield(0).controller = 0
    t.begin_turn(seat=0)
    check("the turn player Holds every battlefield they control (315.2.b.2)",
          t.player(0).points == 1)

    # 471.1.b: the final point needs every battlefield scored that turn.
    t = fresh(first=0)
    t.begin_turn()
    t.player(0).points = 7
    hand_before = len(t.player(0).hand)
    t.score(0, 0, method="Conquer")
    check("a Conquer at 7 points draws instead of winning when a battlefield is unscored (471.1.b.1)",
          t.player(0).points == 7 and len(t.player(0).hand) == hand_before + 1)
    check("a Score whose point was withheld still triggers the battlefield (471.2)",
          any(t.battlefield(0).name in e["text"] and "reads:" in e["text"] for e in t.log)
          or not cards.text(t.battlefield(0).name).strip())
    t.score(0, 1, method="Conquer")
    check("the final point lands once every battlefield has been scored that turn",
          t.player(0).points == 8)
    check("reaching the Victory Score wins the game (472)", t.winner == 0)

    # 472 is "greater than or equal to the Victory Score, AND more points than
    # any opponent". Nothing covered the second half.
    tied = fresh(first=0)
    tied.begin_turn()
    tied.player(0).points = 8
    tied.player(1).points = 8
    tied.check_victory()
    check("a tie at the Victory Score wins for nobody (472)",
          tied.winner is None,
          "reaching 8 is not enough; it must beat every opponent")
    check("a finished game refuses to start another turn",
          raises(lambda: t.begin_turn(), "game is over"))

    # 196: the game ends on the win, mid-phase. Continuing to channel and draw
    # produces a final state that never legally existed.
    t = fresh(first=0)
    t.begin_turn()
    stub_unit(t, 1, "Irelia, Fervent", "bf:0")
    t.battlefield(0).controller = 1
    t.player(1).points = 7
    runes_before = len([r for r in t.runes if r.controller == 1])
    hand_before = len(t.player(1).hand)
    t.end_turn()
    t.begin_turn()
    check("a win during the Scoring Step stops the turn there (196)",
          t.winner == 1
          and len([r for r in t.runes if r.controller == 1]) == runes_before
          and len(t.player(1).hand) == hand_before)

    t = fresh(first=0)
    t.begin_turn()
    t.battlefield(0).controller = 1
    t.cleanup()
    check("control is lost when no units remain there (190.4.c)",
          t.battlefield(0).controller is None)

    # Moving in alone is the commonest way this game is scored, and it does not
    # go through combat — nothing established control, so the point never came.
    t = fresh(first=0)
    t.begin_turn()
    lone = stub_unit(t, 0, "Irelia, Fervent", "base:0")
    t.standard_move(lone.id, "bf:0")
    t.cleanup()
    check("moving alone onto an empty battlefield takes control and Conquers (466.5.d)",
          t.battlefield(0).controller == 0 and t.player(0).points == 1
          and not t.battlefield(0).contested)

    # 190.4.b: while both sides are present a cleanup settles nothing.
    t = fresh(first=0)
    t.begin_turn()
    a = stub_unit(t, 0, "Irelia, Fervent", "base:0")
    stub_unit(t, 1, "Irelia, Fervent", "bf:0")
    t.standard_move(a.id, "bf:0")
    t.cleanup()
    check("a cleanup does not hand control to either side while a combat is staged (190.4.b)",
          t.battlefield(0).controller is None and t.battlefield(0).contested)

    # "Aspirant's Climb" reads "Increase the points needed to win the game by 1".
    # A hard-coded 8 would hand the game over a full point early.
    t = fresh(first=0)
    t.begin_turn()
    t.set_target(9, reason="Aspirant's Climb")
    t.player(0).points = 8
    t.check_victory()
    check("a raised Victory Score is respected, not overridden by the mode's 8",
          t.winner is None)
    t.player(0).points = 9
    t.check_victory()
    check("the raised Victory Score still ends the game when reached", t.winner == 0)

    check("battlefield text is surfaced at setup, where it starts applying",
          any("reads:" in e["text"] for e in fresh(first=0).log))


# -- burn out (431) ------------------------------------------------------

def burn_out():
    t = fresh(first=0)
    t.player(0).main_deck = []
    t.player(0).trash = ["Called Shot"]
    t.draw(0, 1)
    check("drawing from an empty Main Deck reports a Burn Out (431)",
          any("BURNS OUT" in entry["text"] for entry in t.log))

    # 431.2 is a sequence, not a notification. It used to be the log line alone,
    # which made a decked-out player immortal — 431.2.c is the only mechanism by
    # which such a game ever ends.
    t = fresh(first=0)
    p = t.player(0)
    p.trash = list(p.main_deck)[:35]
    p.main_deck = []
    hand_before = len(p.hand)
    opp_before = t.player(1).points
    t.draw(0, 1, reason="draw phase")
    check("burning out recycles the trash into the Main Deck (431.2.b)",
          len(p.main_deck) == 34 and p.trash == [],
          "35 recycled, one of them then drawn")
    check("burning out gives an opponent a point (431.2.c)",
          t.player(1).points == opp_before + 1)
    check("the draw that caused the burn out still completes (431.2.d, 315.4.b.2)",
          len(p.hand) == hand_before + 1)

    # 431.3.a: with the trash empty too, it repeats until someone wins.
    t = fresh(first=0)
    t.player(0).main_deck = []
    t.player(0).trash = []
    t.draw(0, 1)
    check("an empty deck AND an empty trash hands the game to the opponent (431.3.a)",
          t.winner == 1 and t.player(1).points >= t.victory_target,
          f"seat 1 reached {t.player(1).points}")
    check("that win is immediate, without waiting for a cleanup (431.3.c.1)",
          t.winner == 1)


# -- persistence ---------------------------------------------------------

def persistence():
    # first=None so the SHARED stream is actually consumed (115 rolls for first
    # player). With first passed explicitly it never advances, and a check on its
    # restored position compares two untouched generators and proves nothing.
    t = table.Table(list(two_decks()), seed=7).setup()
    t.begin_turn()
    stub_unit(t, 0, "Irelia, Fervent", "bf:0")
    t.battlefield(0).controller = 0
    t.player(0).points = 3
    t.set_target(9, reason="a card said so")
    t.permanents[0].damage = 2
    t.permanents[0].buffs = 1
    t.permanents[0].note = "stunned"
    t.player(0).power = {"Calm": 2}
    raw = json.loads(json.dumps(t.as_dict()))
    back = table.Table.from_dict(raw, list(two_decks()))

    # Read the restored OBJECT, never as_dict() against as_dict(): comparing a
    # serialiser with itself passes just as happily when a field is dropped from
    # both sides, which is exactly how a lost victory_target went unnoticed.
    restored = [
        ("turn", back.turn == t.turn),
        ("phase", back.phase == t.phase),
        ("turn_player", back.turn_player == t.turn_player),
        ("first_player", back.first_player == t.first_player),
        ("victory_target", back.victory_target == 9),
        ("winner", back.winner == t.winner),
        ("points", [p.points for p in back.players] == [p.points for p in t.players]),
        ("power pool", back.player(0).power == {"Calm": 2}),
        ("hands", [p.hand for p in back.players] == [p.hand for p in t.players]),
        ("deck order", [p.main_deck for p in back.players] == [p.main_deck for p in t.players]),
        ("permanent damage", back.permanents[0].damage == 2),
        ("permanent buffs", back.permanents[0].buffs == 1),
        ("permanent note", back.permanents[0].note == "stunned"),
        ("permanent location", back.permanents[0].location == t.permanents[0].location),
        ("battlefield control", [b.controller for b in back.battlefields]
                                == [b.controller for b in t.battlefields]),
        ("scored_by", [b.scored_by for b in back.battlefields]
                      == [b.scored_by for b in t.battlefields]),
        ("next id", back._next_id == t._next_id),
        # The seed alone does not reproduce a game. Every CLI command reloads
        # the table, so a generator restarting at position 0 each time replays
        # numbers the game has already used — same seed, different game.
        ("rng position", back.rng.random() == _next_random(t)),
        ("seat rng positions",
         [back.seat_rng[i].random() for i in (0, 1)]
         == [_next_random_of(t.seat_rng[i]) for i in (0, 1)]),
    ]
    lost = [name for name, ok in restored if not ok]
    check("a saved game restores every field of its state",
          not lost,
          f"lost: {', '.join(lost)}" if lost else f"{len(restored)} fields checked")


def rendering():
    """A render costs tokens, and a game is many renders.

    Reprinting every card's full text on every render was about half a turn's
    output and told the reader nothing they had not just been told.
    """
    import view
    t = fresh(first=0)
    t.begin_turn()
    first = view.render(t, seat=0)
    second = view.render(t, seat=0)
    check("a card's printed text appears the first time it is rendered",
          any(cards.text(n)[:24] in first for n in t.player(0).hand if cards.has_text(n)))
    check("the same render twice does not repeat the text",
          len(second) < len(first),
          f"{len(first)} chars then {len(second)}")
    check("--verbose brings the text back",
          len(view.render(t, seat=0, verbose=True)) > len(second))
    check("what is hidden is the TEXT, never the card's presence",
          all(n in second for n in t.player(0).hand),
          "every card in hand is still listed, with its cost and payability")

    # The saving must survive the game being saved and reloaded, or every
    # command starts over and the reprints come back.
    import json as _json
    back = table.Table.from_dict(_json.loads(_json.dumps(t.as_dict())), list(two_decks()))
    check("what has been seen survives a save and reload",
          back.text_shown == t.text_shown and len(view.render(back, seat=0)) == len(second))


def privacy():
    """108.7.c: a hand is Private Information."""
    import view
    t = fresh(first=0)
    public = "\n".join(view.log_lines(t))
    check("the public log does not name the cards anyone drew (108.7.c)",
          not any(n in public for p in t.players for n in p.hand),
          "`new` printed this log, so both opening hands were on screen before "
          "the first mulligan decision")
    check("the log still shows that a draw happened",
          "draws 4" in public and "(hidden)" in public)
    own = "\n".join(view.log_lines(t, seat=0))
    check("a seat sees its own draws in full",
          all(n in own for n in t.player(0).hand))
    check("and still not the opponent's",
          not any(n in own for n in t.player(1).hand
                  if n not in t.player(0).hand))
    check("a finished game can be reviewed in full",
          all(n in "\n".join(view.log_lines(t, full=True)) for n in t.player(1).hand))


def journalling():
    """Played games are few, so every number carries an n — and no free wins."""
    import journal as j
    import tempfile
    original = j.JOURNAL
    try:
        j.JOURNAL = os.path.join(tempfile.mkdtemp(), "j.jsonl")
        j.record({"deck": "A", "opponent": "A", "winner_deck": "A", "seed": 1})
        rows = j.matchups("A")
        check("a mirror match is not counted as a win (it is 50% by construction)",
              rows and rows[0]["rate"] is None and rows[0]["games"] == 1,
              str(rows))
        j.record({"deck": "A", "opponent": "B", "winner_deck": "B", "seed": 2})
        rows = {r["opponent"]: r for r in j.matchups("A")}
        check("a real matchup is still counted",
              rows["B"]["games"] == 1 and rows["B"]["wins"] == 0)
        low, high = j.wilson(3, 4)
        check("a 3-1 does not read as a confident 75%",
              low < 0.4 and high < 1.0,
              f"95% interval {low:.0%}-{high:.0%}")
    finally:
        j.JOURNAL = original


def atomicity():
    """An action either happens or does not. Half-applied states are unreachable
    by any legal sequence of play, so the table must never produce one."""
    import deck_cli
    t = fresh(first=0)
    t.begin_turn()
    name = next(n for n in t.player(0).main_deck
                if (cards.energy_cost(n) or 0) <= 2 and not cards.power_cost(n))
    readied = len([r for r in t.runes if r.controller == 0 and not r.exhausted])
    hand = list(t.player(0).hand)
    # `cast` pays before the card can turn out not to be in hand.
    try:
        deck_cli.act(t, ["cast", "0", name])
    except RulesError:
        pass
    check("a refused `cast` does not spend the runes it had already paid",
          len([r for r in t.runes if r.controller == 0 and not r.exhausted]) == readied
          and t.player(0).hand == hand,
          "the cost was paid before the card was found missing from hand")

    t = fresh(first=0)
    t.begin_turn()
    oid = stub_unit(t, 0, "Stellacorn Herder", "base:0").id
    try:
        deck_cli.act(t, ["smove", oid, "bf:9"])
    except (RulesError, KeyError):
        pass
    # Re-fetch by id: a rollback rebuilds the board, so any reference taken
    # before it is stale. Every CLI command reloads the table, so this only bites
    # callers holding objects across an action — like this check did.
    unit = t.permanent(oid)
    check("a refused move does not leave the unit exhausted",
          not unit.exhausted and unit.location == "base:0",
          "`standard_move` exhausts before it validates the destination")

    t = fresh(first=0)
    t.begin_turn()
    before = t.as_dict()
    try:
        deck_cli.act(t, ["cast", "0", "Definitely Not A Card"])
    except (RulesError, KeyError):
        pass
    check("a refused action leaves the table byte-identical",
          t.as_dict() == before)

    # A card has to come from somewhere.
    t = fresh(first=0)
    t.begin_turn()
    # A card that is genuinely in no zone of this player's — not merely one the
    # random opening hand happened not to deal.
    absent = next(n for n in t.player(0).main_deck
                  if n not in t.player(0).hand and n not in t.player(0).champion_zone)
    check("a card in no zone cannot be put into play",
          raises(lambda: t.put_into_play(0, absent, "base:0"), "not in seat"))
    check("a name that is not a card at all is refused",
          raises(lambda: t.put_into_play(0, "Not A Real Card", "base:0"), "not a card"))
    check("an effect may put a card into play from a named zone",
          _puts_from_trash(t))


def _puts_from_trash(t):
    p = t.player(0)
    p.trash.append("Stellacorn Herder")
    perm = t.put_into_play(0, "Stellacorn Herder", "base:0", source="trash")
    return perm in t.permanents and "Stellacorn Herder" not in p.trash


def importing():
    """Most decklist sites refuse scripted requests, so the gauntlet is built by
    pasting text. That parser is the only route in, and a name it gets wrong is a
    different card playing every game."""
    import importer

    LIST = """
    Legend: Rengar, Pridestalker
    Champion: Rengar, Trophy Hunter
    Units (30)
    3x Pit Rookie
    3 Inferna
    Nidalee - Cat Form x3
    2x Kinkou Initiate [SFD-123]
    # a comment
    Spells
    3x Punch First
    Runes
    8x Body Rune
    4x Fury Rune
    Battlefields
    1x Seat of Power
    """
    try:
        d = importer.build(LIST, name="fixture")
    except importer.ImportError_ as err:
        check("a well-formed pasted list imports at all", False, str(err)[:90])
        return
    qty = {c["name"]: c["qty"] for c in d["main"]}
    check("every count notation is read the same way",
          qty.get("Pit Rookie") == 3 and qty.get("Inferna") == 3
          and qty.get("Nidalee - Cat Form") == 3 and qty.get("Kinkou Initiate") == 2,
          "'3x N', '3 N' and 'N x3' all appear in lists people actually paste")
    check("a set code after the name is not part of the name",
          "Kinkou Initiate" in qty,
          "bracketed, because cards.find already strips a parenthesised one — "
          "testing the paren form proves nothing about this parser")
    check("cards are filed by type, not by the heading above them",
          [c["name"] for c in d["runes"]] == ["Body Rune", "Fury Rune"]
          and [c["name"] for c in d["battlefields"]] == ["Seat of Power"],
          "headings vary between sites; the card's own type does not")
    check("the legend is taken from its own line and resolved",
          d["legend"] == "Rengar - Pridestalker",
          "written 'Rengar, Pridestalker' — the two spellings must meet")
    check("section headings and comments are not read as cards",
          all(c["name"] not in ("Units", "Spells", "Runes") for c in d["main"]))

    # A wrong card is worse than a refused import.
    try:
        importer.build("Legend: Rengar, Pridestalker\n3x Not A Real Card", name="x")
        bad = False
    except importer.ImportError_ as err:
        bad = "matches no card" in str(err)
    check("an unknown card name refuses the whole import", bad)

    try:
        importer.build("Legend: Rengar, Pridestalker\n3x Master Yi", name="x")
        amb = False
    except importer.ImportError_ as err:
        amb = "ambiguous" in str(err)
    check("an ambiguous card name refuses rather than picking one", amb)

    try:
        importer.build("3x Pit Rookie", name="x")
        noleg = False
    except importer.ImportError_ as err:
        noleg = "no legend" in str(err)
    check("a list with no legend is refused (it decides Domain Identity)", noleg)

    # Every problem at once: a list with three bad names should name three.
    try:
        importer.build("Legend: Rengar, Pridestalker\n1x Nope One\n1x Nope Two", name="x")
        both = False
    except importer.ImportError_ as err:
        both = str(err).count("matches no card") == 2
    check("every bad name is reported, not just the first",
          both, "fixing a pasted list one error per run is why people give up")

    check("an imported deck records its own provenance",
          d["source"]["site"] == "imported"
          and bool(re.match(r"^\d{4}-\d{2}-\d{2}$", d["source"].get("fetched", ""))),
          "a decklist goes stale; without a date you cannot tell a current list "
          "from one two sets old")

    d2 = importer.build("Legend: Irelia, Blade Dancer\n3x Irelia, Fervent\n3x Irelia, Graceful",
                        name="ambiguous champion")
    check("an ambiguous Chosen Champion is left unset and explained",
          d2["chosen_champion"] is None and "only the pilot knows" in d2.get("chosen_champion_note", ""))


def documentation():
    """SKILL.md is the procedure an agent follows. Its examples have to run.

    The review found a documented `precombat` example that was not runnable and
    a setup message telling every reader to use an action that did not exist.
    Prose drifts from code silently; this makes it fail loudly.
    """
    import deck_cli
    skill_md = os.path.join(os.path.dirname(HERE), "SKILL.md")
    text = open(skill_md, encoding="utf-8").read()

    t = fresh(first=0)
    t.begin_turn()
    commands = {"decks", "check", "card", "analyze", "report", "new", "state",
                "do", "log", "games", "record", "journal", "selftest", "mutants", "help"}

    # The verbs the CLI's own help advertises must all be real.
    help_text = deck_cli.__doc__ or ""
    import io, contextlib
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        deck_cli.cmd_help(None)
    # Scan only the action reference; verbs appear both at line start and
    # paired mid-line there, and the usage header above it is not a verb list.
    section = buf.getvalue().split("actions for `do`", 1)[-1]
    advertised = set(re.findall(r"\b([a-z]+) [<\[]", section)) - commands
    unknown = []
    for verb in sorted(advertised):
        try:
            deck_cli._act(t, [verb])
        except RulesError as err:
            if "unknown action" in str(err):
                unknown.append(verb)
        except Exception:
            pass  # wrong arity is fine; the verb exists
    check("every action the CLI advertises exists", not unknown,
          f"missing: {', '.join(unknown)}" if unknown else f"{len(advertised)} verbs")

    # Every `do '...'` example in SKILL.md must parse and name real verbs.
    examples = re.findall(r"do '([^']+)'", text)
    bad = []
    for example in examples:
        for argv in deck_cli.split_actions(example):
            if argv and argv[0] not in advertised:
                bad.append(argv[0])
    check("every action in SKILL.md's own examples is real", not bad,
          f"{len(examples)} example(s); unknown: {', '.join(bad)}" if bad
          else f"{len(examples)} example(s) checked")

    # Anything the table tells a reader to run must also be real. The setup
    # message told every reader to use `set-target`, which never existed.
    told = set(re.findall(r"`([a-z][a-z-]+)", "\n".join(e["text"] for e in t.log)))
    bogus = sorted(v for v in told if v not in commands and v not in advertised)
    check("the table never tells the reader to run something that does not exist",
          not bogus, f"log mentions: {', '.join(bogus)}" if bogus else "")

    for phrase, ok in (
        ("channel 2 runes", MODE_CHANNEL == 2),
        ("first to 8 points", deckfile.MODE["victory_score"] == 8),
        ("opening hand of 4", deckfile.MODE["opening_hand"] == 4),
    ):
        check(f"SKILL.md's numbers match the mode: {phrase}", ok)


MODE_CHANNEL = deckfile.MODE["channel_per_turn"]


def action_scripts():
    import deck_cli
    check(
        "an action script splits on ; without cutting inside quotes",
        deck_cli.split_actions('note "drew 1; kept it"; draw 0 2')
        == [["note", "drew 1; kept it"], ["draw", "0", "2"]],
        "a semicolon in a note used to take the whole batch down",
    )
    check(
        "quoted card names survive the split",
        deck_cli.split_actions('cast 0 "Stellacorn Herder" bf:0')
        == [["cast", "0", "Stellacorn Herder", "bf:0"]],
    )
    check("an empty script is not an error", deck_cli.split_actions("") == [])


def main():
    print("deck-lab selftest\n")
    for section in (
        card_lookup, deck_legality, setup_rules, turn_structure, resources,
        paying, movement, combat, scoring, burn_out, persistence, rendering,
        privacy, journalling, atomicity, importing, documentation, action_scripts,
    ):
        print(f"{section.__name__}:")
        section()
        print()
    print(f"{RAN[0] - len(FAILS)}/{RAN[0]} passed")
    if FAILS:
        print("\nFAILED:")
        for name in FAILS:
            print(f"  - {name}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
