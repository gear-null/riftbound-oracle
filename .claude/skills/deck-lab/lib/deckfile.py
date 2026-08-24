"""Load a deck, and check it against the deck-construction rules (103).

Legality is checked here rather than left to the reader because an illegal deck
does not fail loudly during a game — it just quietly plays a card it should not
have, and every result taken from that game is wrong.

What is checked is exactly what the rules make checkable from card data. What is
not checkable is reported as unchecked rather than passed silently; see
`Legality.unchecked`.
"""
import glob
import json
import os

import cards

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL = os.path.dirname(HERE)
GAUNTLET_DIR = os.path.join(SKILL, "gauntlet")
DECKS_DIR = os.path.join(SKILL, "decks")

#: 1v1 Duel (485) — the only sanctioned mode this table implements.
MODE = {
    "name": "1v1 (Duel)",
    "players": 2,
    "victory_score": 8,
    "battlefields_in_play": 2,
    "battlefields_per_deck": 3,
    "opening_hand": 4,
    "channel_per_turn": 2,
    "main_deck_min": 40,
    "rune_deck_size": 12,
    "max_copies": 3,
    "max_signature": 3,
}


class Deck:
    """A deck as declared. Nothing here is shuffled or drawn — see `table`."""

    def __init__(self, raw, path=None):
        self.path = path
        self.raw = raw
        self.name = raw.get("name") or "untitled"
        self.legend = raw["legend"]
        self.chosen_champion = raw.get("chosen_champion") or raw.get("chosenChampion")
        self.main = [(c["name"], int(c["qty"])) for c in raw.get("main", [])]
        self.runes = [(c["name"], int(c["qty"])) for c in raw.get("runes", [])]
        self.battlefields = [(c["name"], int(c["qty"])) for c in raw.get("battlefields", [])]
        self.source = raw.get("source") or {}

    # -- expansion -------------------------------------------------------

    def main_cards(self):
        """Every Main Deck card, one entry per physical copy.

        The Chosen Champion is NOT here: rule 112 puts it in the Champion Zone
        during setup, so it is never shuffled into the deck and never drawn.
        """
        out = []
        for name, qty in self.main:
            copies = qty
            if self.chosen_champion and _same(name, self.chosen_champion):
                copies -= 1
            out.extend([name] * max(copies, 0))
        return out

    def rune_cards(self):
        out = []
        for name, qty in self.runes:
            out.extend([name] * qty)
        return out

    def battlefield_cards(self):
        out = []
        for name, qty in self.battlefields:
            out.extend([name] * qty)
        return out

    def domain_identity(self):
        """The legend's domains — what every other card must fit inside (103.1.b)."""
        return set(cards.domains(self.legend)) if cards.find(self.legend) else set()

    def to_json(self):
        return {
            "name": self.name,
            "legend": self.legend,
            "chosen_champion": self.chosen_champion,
            "main": [{"name": n, "qty": q} for n, q in self.main],
            "runes": [{"name": n, "qty": q} for n, q in self.runes],
            "battlefields": [{"name": n, "qty": q} for n, q in self.battlefields],
            "source": self.source,
        }


def _same(a, b):
    ca, cb = cards.find(a), cards.find(b)
    if ca and cb:
        return ca["name"] == cb["name"]
    return a.strip().lower() == b.strip().lower()


class Legality:
    def __init__(self):
        self.errors = []
        self.warnings = []
        #: Rules this data cannot decide, named so they are not mistaken for passes.
        self.unchecked = []

    @property
    def legal(self):
        return not self.errors

    def as_dict(self):
        return {
            "legal": self.legal,
            "errors": self.errors,
            "warnings": self.warnings,
            "unchecked": self.unchecked,
        }


def check(deck, mode=MODE):
    """Check a deck against rule 103, for the given mode of play."""
    r = Legality()

    unknown = [n for n, _ in deck.main + deck.runes + deck.battlefields if not cards.find(n)]
    if not cards.find(deck.legend):
        unknown.append(deck.legend)
    if unknown:
        # Every later check reads stats off the pool, so an unknown card makes
        # the rest of this report meaningless rather than merely incomplete.
        r.errors.append(f"not in the card pool: {', '.join(sorted(set(unknown)))}")
        return r

    if cards.card_type(deck.legend) != cards.LEGEND:
        r.errors.append(f"{deck.legend} is not a Legend (103.1)")

    # 103.2 — main deck size. The Chosen Champion sits in the Champion Zone but
    # is still one of the deck's cards for construction purposes.
    total_main = sum(q for _, q in deck.main)
    if total_main < mode["main_deck_min"]:
        r.errors.append(f"Main Deck has {total_main} cards, minimum is {mode['main_deck_min']} (103.2)")

    # 103.2.b — at most 3 copies of a name.
    for name, qty in deck.main:
        if qty > mode["max_copies"]:
            r.errors.append(f"{qty}x {name} exceeds the {mode['max_copies']}-copy limit (103.2.b)")

    # 103.3.a — exactly 12 runes.
    total_runes = sum(q for _, q in deck.runes)
    if total_runes != mode["rune_deck_size"]:
        r.errors.append(f"Rune Deck has {total_runes} runes, must be {mode['rune_deck_size']} (103.3.a)")

    # 103.4 — battlefield count, and no duplicate names.
    total_bf = sum(q for _, q in deck.battlefields)
    if total_bf != mode["battlefields_per_deck"]:
        r.errors.append(
            f"{total_bf} battlefields, mode requires {mode['battlefields_per_deck']} (103.4.a)"
        )
    for name, qty in deck.battlefields:
        if qty > 1:
            r.errors.append(f"{qty}x {name}: battlefields must have distinct names (103.4.c)")

    # 103.1.b — domain identity. A card with two domains needs both of them.
    identity = deck.domain_identity()
    for name, _ in deck.main + deck.runes + deck.battlefields:
        card_domains = set(cards.domains(name))
        if card_domains and not card_domains.issubset(identity):
            outside = ", ".join(sorted(card_domains - identity))
            r.errors.append(
                f"{name} is {'/'.join(sorted(card_domains))}, outside the deck's "
                f"{'/'.join(sorted(identity)) or 'empty'} identity — {outside} (103.1.b.4)"
            )

    # 103.2.d — at most 3 Signature cards, all bearing the legend's champion tag.
    legend_tags = set(cards.tags(deck.legend))
    signatures = [(n, q) for n, q in deck.main if cards.is_signature(n)]
    sig_total = sum(q for _, q in signatures)
    if sig_total > mode["max_signature"]:
        r.errors.append(f"{sig_total} Signature cards, limit is {mode['max_signature']} (103.2.d.1)")
    for name, _ in signatures:
        if legend_tags and not (set(cards.tags(name)) & legend_tags):
            r.errors.append(
                f"{name} is a Signature card without the legend's champion tag "
                f"({'/'.join(sorted(legend_tags))}) (103.2.d.2)"
            )

    # 103.2.a — the Chosen Champion.
    if not deck.chosen_champion:
        r.errors.append("no chosen_champion set — the Champion Zone would start empty (103.2.a.1)")
    else:
        cc = deck.chosen_champion
        if not cards.find(cc):
            r.errors.append(f"chosen_champion {cc!r} is not in the card pool")
        else:
            if not cards.is_champion(cc) or cards.card_type(cc) != cards.UNIT:
                r.errors.append(f"{cc} is not a champion unit (103.2.a.2)")
            if legend_tags and not (set(cards.tags(cc)) & legend_tags):
                r.errors.append(
                    f"{cc} does not carry the legend's champion tag "
                    f"({'/'.join(sorted(legend_tags))}) (103.2.a.2)"
                )
            if not any(_same(n, cc) for n, _ in deck.main):
                r.errors.append(f"{cc} is the Chosen Champion but is not in the Main Deck (103.2)")

    # Format legality (103.2.e) depends on a banned/restricted list this corpus
    # does not carry. Saying nothing would read as "checked and fine".
    r.unchecked.append("card legality for a specific Format (103.2.e) — no ban list in the corpus")
    return r


def load(path):
    with open(path, encoding="utf-8") as fh:
        return Deck(json.load(fh), path=path)


def resolve(name_or_path):
    """A deck by path, by filename, or by slug — gauntlet first, then decks/."""
    if os.path.isfile(name_or_path):
        return load(name_or_path)
    stem = os.path.splitext(os.path.basename(name_or_path))[0].lower()
    for candidate in available():
        if os.path.splitext(os.path.basename(candidate))[0].lower() == stem:
            return load(candidate)
    matches = [c for c in available() if stem in os.path.basename(c).lower()]
    if len(matches) == 1:
        return load(matches[0])
    if len(matches) > 1:
        raise KeyError(
            f"{name_or_path!r} matches {len(matches)} decks: "
            + ", ".join(os.path.basename(m) for m in sorted(matches)[:6])
        )
    raise KeyError(f"no deck named {name_or_path!r} in gauntlet/ or decks/")


def available():
    return sorted(
        glob.glob(os.path.join(GAUNTLET_DIR, "*.json")) + glob.glob(os.path.join(DECKS_DIR, "*.json"))
    )


def save(deck, path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(deck.to_json(), fh, indent=1, ensure_ascii=False)
    return path
