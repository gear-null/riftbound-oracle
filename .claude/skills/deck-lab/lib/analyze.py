"""Deck math: what the deck does before anybody makes a decision.

This is the half of deck evaluation that needs no player. Whether a hand can
cast anything on turn 3, how often a domain is missing when a card needs it,
how much of the deck is stranded above the curve — all of that is decided by
the shuffle and the channel rate, not by skill. So it can be measured exactly,
at a hundred thousand games, in a second.

The numbers here are therefore the *confident* part of a deck report. Anything
that depends on how the deck is piloted belongs in played games, where the
sample is small and has to be labelled as such.
"""
import random
from collections import Counter

import cards
from deckfile import MODE


def _requirement(name):
    """(energy, power, allowed domains) for one card."""
    return (
        cards.energy_cost(name) or 0,
        cards.power_cost(name) or 0,
        set(cards.domains(name)),
    )


def castable(name, rune_domains, requirement=None):
    """Could this card be paid for with these runes on the board?

    A rune pays either 1 Energy (by exhausting) or 1 Power of its domain (by
    recycling) — never both. So a card needs `energy + power` runes in total,
    and `power` of them must carry one of the card's domains.
    """
    energy, power, domains = requirement or _requirement(name)
    total = len(rune_domains)
    if energy + power > total:
        return False
    if power:
        matching = sum(1 for d in rune_domains if not domains or d in domains)
        if matching < power:
            return False
    return True


def simulate(deck, turns=8, trials=20000, on_the_play=True, seed=1, mode=MODE):
    """Monte Carlo over shuffles: what the deck can do, turn by turn.

    No decisions are made. Cards are not played, so nothing is spent — this
    measures what was *available*, which is the ceiling a pilot plays inside.
    """
    rng = random.Random(seed)
    main = deck.main_cards()
    runes = deck.rune_cards()
    reqs = {n: _requirement(n) for n in set(main)}

    opening = mode["opening_hand"]
    per_turn = mode["channel_per_turn"]
    extra = 0 if on_the_play else 1

    # Per turn: how often at least one card in hand was castable, how many
    # were, and how much of the hand was stranded.
    any_play = [0] * (turns + 1)
    castable_count = [0] * (turns + 1)
    hand_size = [0] * (turns + 1)
    stranded = [0] * (turns + 1)
    rune_domains_in_deck = {cards.domains(n)[0] for n in runes if cards.domains(n)}
    domain_online = {d: [0] * (turns + 1) for d in rune_domains_in_deck}
    power_denied = [0] * (turns + 1)

    for _ in range(trials):
        deck_order = main[:]
        rng.shuffle(deck_order)
        rune_order = runes[:]
        rng.shuffle(rune_order)
        hand = deck_order[:opening]
        drawn = opening
        board_runes = []

        for turn in range(1, turns + 1):
            take = per_turn + (extra if turn == 1 else 0)
            board_runes.extend(rune_order[len(board_runes):len(board_runes) + take])
            rune_domains = [cards.domains(r)[0] if cards.domains(r) else None for r in board_runes]
            if drawn < len(deck_order):
                hand.append(deck_order[drawn])
                drawn += 1

            playable = [n for n in hand if castable(n, rune_domains, reqs[n])]
            any_play[turn] += 1 if playable else 0
            castable_count[turn] += len(playable)
            hand_size[turn] += len(hand)
            stranded[turn] += len(hand) - len(playable)
            for d in domain_online:
                if d in rune_domains:
                    domain_online[d][turn] += 1
            # A card that only fails on its Power requirement is a fixing
            # problem, not a curve problem — worth separating, because the two
            # have different fixes.
            for n in hand:
                e, p, doms = reqs[n]
                if p and e + p <= len(rune_domains):
                    if sum(1 for x in rune_domains if not doms or x in doms) < p:
                        power_denied[turn] += 1
                        break

    def rate(series):
        return [round(series[t] / trials, 4) for t in range(turns + 1)]

    def mean(series):
        return [round(series[t] / trials, 2) for t in range(turns + 1)]

    return {
        "trials": trials,
        "turns": turns,
        "on_the_play": on_the_play,
        "has_a_play": rate(any_play),
        "castable_in_hand": mean(castable_count),
        "hand_size": mean(hand_size),
        "stranded_in_hand": mean(stranded),
        "domain_online": {d: rate(s) for d, s in domain_online.items()},
        "power_denied": rate(power_denied),
    }


def composition(deck):
    """What the deck is made of — the part that needs no simulation at all."""
    main = deck.main_cards()
    by_type = Counter(cards.card_type(n) for n in main)
    curve = Counter(cards.energy_cost(n) or 0 for n in main)
    power = Counter(cards.power_cost(n) or 0 for n in main)
    might = [cards.might(n) for n in main if cards.might(n) is not None]
    runes = Counter(cards.domains(n)[0] if cards.domains(n) else "—" for n in deck.rune_cards())

    with_text = [n for n in main if cards.has_text(n)]
    # A card the engine cannot resolve on its own is one the reader must
    # resolve. Stating the share up front is what keeps a game log honest.
    return {
        "main_deck_size": len(main) + (1 if deck.chosen_champion else 0),
        "shuffled_cards": len(main),
        "by_type": dict(by_type),
        "curve": {str(k): v for k, v in sorted(curve.items())},
        "power_costs": {str(k): v for k, v in sorted(power.items())},
        "average_energy": round(sum(cards.energy_cost(n) or 0 for n in main) / max(len(main), 1), 2),
        "average_might": round(sum(might) / len(might), 2) if might else None,
        "rune_split": dict(runes),
        "cards_with_text": len(with_text),
        "vanilla_cards": len(main) - len(with_text),
        "text_share": round(len(with_text) / max(len(main), 1), 3),
        "domain_identity": sorted(deck.domain_identity()),
        "ambiguous_power_split": sorted({
            n for n in set(main)
            if (cards.power_cost(n) or 0) and len(cards.domains(n)) > 1
        }),
    }


def analyse(deck, trials=20000, turns=8, seed=1):
    return {
        "deck": deck.name,
        "legend": deck.legend,
        "chosen_champion": deck.chosen_champion,
        "composition": composition(deck),
        "on_the_play": simulate(deck, turns=turns, trials=trials, on_the_play=True, seed=seed),
        "on_the_draw": simulate(deck, turns=turns, trials=trials, on_the_play=False, seed=seed + 1),
    }
