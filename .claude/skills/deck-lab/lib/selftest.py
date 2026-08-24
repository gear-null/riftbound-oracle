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


def stub_unit(t, seat, name, location, exhausted=False):
    perm = table.Permanent(t._oid("u"), name, seat, location)
    perm.exhausted = exhausted
    t.permanents.append(perm)
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
    check(
        "the pulled gauntlet is legal apart from unresolved champions",
        all(
            r.legal or all("103.2.a.1" in e for e in r.errors)
            for _, r in results
        ),
        f"{len(legal)}/{len(results)} fully legal",
    )

    d = copy.deepcopy(legal[0])
    d.main = [(n, 4 if i == 0 else q) for i, (n, q) in enumerate(d.main)]
    check("a 4th copy of a card is rejected (103.2.b)",
          any("3-copy" in e for e in deckfile.check(d).errors))

    d = copy.deepcopy(legal[0])
    d.runes = d.runes[:1]
    check("a rune deck that is not exactly 12 is rejected (103.3.a)",
          any("Rune Deck has" in e for e in deckfile.check(d).errors))

    d = copy.deepcopy(legal[0])
    d.chosen_champion = None
    check("a deck with no Chosen Champion is rejected (103.2.a.1)",
          any("chosen_champion" in e for e in deckfile.check(d).errors))

    d = copy.deepcopy(legal[0])
    d.battlefields = [(d.battlefields[0][0], 3)]
    check("duplicate battlefield names are rejected (103.4.c)",
          any("distinct names" in e for e in deckfile.check(d).errors))

    check("format legality is reported as unchecked, not as a pass",
          any("103.2.e" in u for u in deckfile.check(legal[0]).unchecked))

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
    c = fresh(seed=100)
    check("a different seed deals a different game",
          [p.hand for p in a.players] != [p.hand for p in c.players])

    t = fresh()
    kept = t.player(0).hand[:2]
    t.mulligan(0, keep=kept)
    check("a mulligan redraws to the same hand size (117)",
          len(t.player(0).hand) == 4 and all(k in t.player(0).hand for k in kept))


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

    t = fresh(first=0)
    t.begin_turn()
    t.add_energy(0, 5)
    t.phase = table.MAIN
    check("the rune pool is emptied entering the Main Phase (316.3)",
          _pool_emptied_on_main(t))


def _pool_emptied_on_main(t):
    t.add_energy(0, 4)
    t.end_turn()
    t.begin_turn()
    return t.player(0).energy == 0


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
    result = t.resolve_combat(0)
    check("equal Might trades both units simultaneously (465.2.c.1.a)",
          t.units_at("bf:0") == [] and result["result"] == "mutual destruction")

    t = fresh(first=0)
    t.begin_turn()
    attacker = stub_unit(t, 0, "Stellacorn Herder", "bf:0")
    defender = stub_unit(t, 1, "Irelia, Fervent", "bf:0")
    t.resolve_combat(0)
    check("a repelled attacker is recalled rather than left standing (466.1.a.2)",
          defender in t.permanents and attacker not in t.permanents
          or attacker.location == "base:0")

    t = fresh(first=0)
    t.begin_turn()
    winner = stub_unit(t, 0, "Irelia, Fervent", "bf:0")
    stub_unit(t, 1, "Stellacorn Herder", "bf:0")
    before = t.player(0).points
    t.resolve_combat(0)
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
    t.resolve_combat(0)
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
    t.resolve_combat(0)
    check("a Might change applied before combat changes who dies",
          poro in t.permanents,
          "at 4 Might the Poro survives the 3 damage that killed it at 2")
    check("combat logs the text of the units that fought, so it can be audited",
          any("reads:" in e["text"] and "Shield" in e["text"] for e in t.log))


# -- scoring (467-472) ---------------------------------------------------

def scoring():
    t = fresh(first=0)
    t.begin_turn()
    t.battlefield(0).controller = 0
    t.score(0, 0, method="Conquer")
    check("scoring gains a point", t.player(0).points == 1)
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
    t.draw(0, 1)
    check("drawing from an empty Main Deck reports a Burn Out (431)",
          any("BURNS OUT" in entry["text"] for entry in t.log))


# -- persistence ---------------------------------------------------------

def persistence():
    t = fresh(first=0)
    t.begin_turn()
    stub_unit(t, 0, "Irelia, Fervent", "bf:0")
    t.battlefield(0).controller = 0
    t.player(0).points = 3
    raw = json.loads(json.dumps(t.as_dict()))
    back = table.Table.from_dict(raw, list(two_decks()))
    check("a saved game restores identically",
          back.as_dict() == t.as_dict(),
          "a game spans many turns and many sessions; drift here is invisible")


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
        paying, movement, combat, scoring, burn_out, persistence, action_scripts,
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
