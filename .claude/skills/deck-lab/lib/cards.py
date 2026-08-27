"""The card pool, and the one lookup everything else goes through.

Nothing here interprets card text. `text` is returned exactly as printed so the
agent reading it is reading the card, not a paraphrase of it — the same reason
`rules-report` keeps `[Keyword]` brackets and `:rb_energy_1:` shortcodes intact.
"""
import json
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
# ADR 0004: never resolve anything outside the skill folder at import time.
DATA = os.path.join(os.path.dirname(HERE), "data", "cards.json")

_POOL = None

#: Card categories, as rule 133 classifies them.
UNIT, SPELL, GEAR, RUNE, BATTLEFIELD, LEGEND = "Unit", "Spell", "Gear", "Rune", "Battlefield", "Legend"

#: The six domains (164.1).
DOMAINS = ("Fury", "Calm", "Mind", "Body", "Chaos", "Order")

#: How the API spells what the rules call "domainless" (135.2.e.6.b, 187.1).
#: It is a value in the domain list, not an absence, so reading the list
#: literally makes 69 cards — every colorless battlefield among them — look
#: like they violate the domain identity of every deck that plays them.
COLORLESS = "Colorless"


def pool():
    """The whole card index, loaded once."""
    global _POOL
    if _POOL is None:
        with open(DATA, encoding="utf-8") as fh:
            _POOL = json.load(fh)
    return _POOL


def _variants(name):
    """The spellings of one card name that different sources use.

    Riftcodex writes a subtitled card `Master Yi - Wuju Bladesman`; decklist
    sites write `Master Yi, Wuju Bladesman`. Every legend and every champion is
    subtitled, so matching the literal string resolves none of them.

    Nothing looser is tried. A fuzzy match that returns a DIFFERENT card is
    worse than returning none: the wrong card gets shuffled into the deck and
    played as if the list had named it.
    """
    if not name:
        # A lookup of "no name" is "no card". Raising here turned a reportable
        # legality error — a deck with no Chosen Champion set — into a traceback
        # that took the whole check down with it.
        return []
    base = re.sub(r"\s*\(.*?\)\s*$", "", name).strip().lower()
    seen, out = set(), []
    for v in (base, base.replace(", ", " - "), base.replace(" - ", ", ")):
        if v not in seen:
            seen.add(v)
            out.append(v)
    return out


def find(name):
    """One card by name, or None. Never a near miss, never a coin flip.

    The index carries base-name aliases: `master yi` is a key, because a rules
    question may well name a champion without its subtitle. For a rules answer
    that is helpful; for a deck it is dangerous, because "Master Yi" names six
    different champion units and picking one of them would shuffle a card into
    the deck that the list never asked for. Aliases the index flags as
    `ambiguous` are therefore refused here — see `candidates` to see them.
    """
    p = pool()
    for key in _variants(name):
        entry = p.get(key)
        if entry is not None and not entry.get("ambiguous"):
            return entry
    return None


def candidates(name):
    """The cards an ambiguous name could mean, so a caller can say which."""
    p = pool()
    for key in _variants(name):
        entry = p.get(key)
        if entry is not None and entry.get("ambiguous"):
            return list(entry["ambiguous"])
    return []


def require(name):
    card = find(name)
    if card is None:
        options = candidates(name)
        if options:
            raise KeyError(
                f"{name!r} is ambiguous — it could be any of: {', '.join(options)}"
            )
        raise KeyError(f"no card named {name!r} in the pool")
    return card


def stats(name):
    return require(name)["stats"]


def energy_cost(name):
    """Printed Energy cost. 0 is a real cost; absent means the card has none."""
    return stats(name).get("energy")


def power_cost(name):
    """Printed Power cost — a count, whose domain comes from the card (163.2)."""
    return stats(name).get("power")


def domains(name):
    """The card's domains for identity purposes — empty when it is domainless.

    Rule 103.1.b constrains only cards that HAVE domains: a colorless card is
    permitted in any identity. Every gauntlet deck failed legality until this
    distinction was made, because all 24 of them run colorless battlefields.
    """
    return [d for d in (stats(name).get("domain") or []) if d != COLORLESS]


def printed_domains(name):
    """The domain list exactly as the data carries it, Colorless included."""
    return list(stats(name).get("domain") or [])


def card_type(name):
    return stats(name).get("type")


def supertype(name):
    return stats(name).get("supertype")


def tags(name):
    return list(stats(name).get("tags") or [])


def might(name):
    return stats(name).get("might")


def text(name):
    """Printed rules text, verbatim."""
    return require(name).get("text", "")


_CHAMPION_TAGS = None


def champion_tags():
    """The tags that name a champion, as opposed to a trait or a region.

    103.2.a.2 binds a Chosen Champion to its Legend by CHAMPION tag, and 103.2.d.2
    scopes Signature cards the same way. Matching on any shared tag was too
    loose: a Kennen legend is tagged ['Yordle', 'Kennen'], so Fizz — also a
    Yordle — passed as a legal Chosen Champion for it.

    Derived rather than listed: a champion tag is one that is also the name a
    champion card is printed under ("Kennen" is the base of "Kennen - Heart of
    the Tempest"; "Yordle" is the base of nothing). That keeps working when a
    set adds champions, which a hardcoded list would not.
    """
    global _CHAMPION_TAGS
    if _CHAMPION_TAGS is None:
        bases = set()
        for entry in pool().values():
            # "Kennen, Keeper of Balance" has no space before its comma, and
            # "Ahri, Nine-Tailed Fox" has a hyphen with no space after it — so
            # the separator is punctuation followed by whitespace.
            base = re.split(r"\s*[-,]\s+", entry["name"])[0].strip()
            if entry["stats"].get("supertype") == "Champion" and base:
                bases.add(base)
        _CHAMPION_TAGS = {
            t for entry in pool().values()
            for t in (entry["stats"].get("tags") or [])
            if t in bases
        }
    return _CHAMPION_TAGS


def champion_tags_of(name):
    """Just this card's champion tags — its traits and regions dropped.

    An absent name has no tags rather than raising: a deck under construction may
    not have a legend yet, and a crash there takes a whole legality report down.
    """
    if not name or find(name) is None:
        return set()
    return {t for t in tags(name) if t in champion_tags()}


def is_champion(name):
    return supertype(name) == "Champion"


def is_signature(name):
    return supertype(name) == "Signature"


def has_text(name):
    """Does this card do anything beyond its stats?

    Used to report how much of a deck is vanilla — a unit with no text plays
    identically whoever is holding it, and one with text does not.
    """
    return bool((text(name) or "").strip())
