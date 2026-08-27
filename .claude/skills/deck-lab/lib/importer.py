"""Turn a pasted decklist into a deck file.

Most decklist sites cannot be scraped — measured this session, four of six
refuse scripted requests outright (403 or a reset connection). A gauntlet built
only from the one site that allows it is a gauntlet missing whole archetypes,
and you find that out in the middle of an analysis rather than up front.

So the import path takes TEXT. Anything a person can copy — a tournament
registration sheet, a site that blocks scripts, a screenshot someone typed out —
becomes a testable opponent. The parser is deliberately forgiving about layout
and completely unforgiving about card identity: a name it cannot resolve to
exactly one card is reported, never guessed, because a wrong card silently
changes every game the deck plays.
"""
import datetime
import os
import re

import cards
import deckfile

#: Lines that are structure, not cards.
_SECTION = re.compile(
    r"^\s*(main\s*deck|maindeck|deck|units?|spells?|gear|runes?|battlefields?|"
    r"champions?|legend|sideboard|total)\b\s*[:(\-]?\s*\d*\s*\)?\s*$",
    re.I,
)
_COMMENT = re.compile(r"^\s*(#|//|--)")
#: "Legend: Renekton - Butcher of the Sands"
_FIELD = re.compile(r"^\s*(legend|chosen\s*champion|champion)\s*[:\-]\s*(.+?)\s*$", re.I)

#: "3x Name" / "3 Name" / "Name x3" / "Name" — plus a trailing set code to drop.
_LEADING = re.compile(r"^\s*(\d{1,2})\s*[xX*]?\s+(.+?)\s*$")
_TRAILING = re.compile(r"^\s*(.+?)\s*[xX*]\s*(\d{1,2})\s*$")
_CODE = re.compile(r"\s*[\(\[]\s*[A-Z]{2,4}[- ]?\d{1,4}[a-zA-Z]?\s*[\)\]]\s*$")


class ImportError_(Exception):
    """The list could not be turned into a deck. Carries every reason at once."""


def _clean(line):
    line = line.split("//")[0]
    line = _CODE.sub("", line)
    return line.strip().rstrip(",;")


def parse_lines(text):
    """[(qty, name)] plus any explicit legend/champion, from free-form text."""
    entries, fields = [], {}
    for raw in text.splitlines():
        if not raw.strip() or _COMMENT.match(raw):
            continue
        field = _FIELD.match(raw)
        if field:
            key = "champion" if "champion" in field.group(1).lower() else "legend"
            fields[key] = _clean(field.group(2))
            continue
        if _SECTION.match(raw):
            continue
        line = _clean(raw)
        if not line:
            continue
        m = _LEADING.match(line)
        if m:
            entries.append((int(m.group(1)), m.group(2).strip()))
            continue
        m = _TRAILING.match(line)
        if m:
            entries.append((int(m.group(2)), m.group(1).strip()))
            continue
        # A bare name is one copy.
        entries.append((1, line))
    return entries, fields


def _resolve(name):
    card = cards.find(name)
    if card:
        return card, None
    options = cards.candidates(name)
    if options:
        return None, f"{name!r} is ambiguous — write one of: {', '.join(options)}"
    return None, f"{name!r} matches no card in the pool"


def build(text, name=None, source=None, legend=None, champion=None, today=None):
    """A deck dict from pasted text. Raises with EVERY problem, not just the first."""
    entries, fields = parse_lines(text)
    legend = legend or fields.get("legend")
    champion = champion or fields.get("champion")

    problems, main, runes, battlefields = [], {}, {}, {}
    found_legend = None
    for qty, raw_name in entries:
        card, why = _resolve(raw_name)
        if why:
            problems.append(why)
            continue
        kind = card["stats"]["type"]
        target = {cards.RUNE: runes, cards.BATTLEFIELD: battlefields}.get(kind, main)
        if kind == cards.LEGEND:
            # A legend listed among the cards is the deck's legend, not a card in it.
            found_legend = found_legend or card["name"]
            continue
        target[card["name"]] = target.get(card["name"], 0) + qty

    if legend:
        card, why = _resolve(legend)
        if why:
            problems.append(f"legend: {why}")
        else:
            found_legend = card["name"]
    if not found_legend:
        problems.append(
            "no legend — add a 'Legend: <name>' line or pass --legend, since the "
            "legend decides the deck's whole Domain Identity (103.1.b)"
        )
    if problems:
        raise ImportError_("\n".join(f"  {p}" for p in problems))

    deck = {
        "name": name or "imported deck",
        "legend": found_legend,
        "chosen_champion": None,
        "main": [{"name": n, "qty": q} for n, q in sorted(main.items())],
        "runes": [{"name": n, "qty": q} for n, q in sorted(runes.items())],
        "battlefields": [{"name": n, "qty": q} for n, q in sorted(battlefields.items())],
    }
    # Provenance is recorded for an imported deck exactly as for a pulled one:
    # a decklist goes stale, and "where did this come from and when" is the only
    # way to tell a current tournament list from one two sets old. A pasted
    # registration sheet legitimately has no URL, so that field is optional and
    # the date is not.
    deck["source"] = {
        "site": "imported",
        "meta": True,
        "fetched": today or datetime.date.today().isoformat(),
    }
    if source:
        deck["source"]["url"] = source

    resolved, note = resolve_champion(deck, champion)
    deck["chosen_champion"] = resolved
    if note:
        deck["chosen_champion_note"] = note
    return deck


def resolve_champion(deck, explicit=None):
    """The Chosen Champion, bound by CHAMPION tag (103.2.a.2). Never guessed."""
    if explicit:
        card = cards.find(explicit)
        return (card["name"] if card else explicit), None
    legend_tags = cards.champion_tags_of(deck["legend"])
    options = [
        c["name"] for c in deck["main"]
        if cards.is_champion(c["name"])
        and cards.card_type(c["name"]) == cards.UNIT
        and (not legend_tags or (cards.champion_tags_of(c["name"]) & legend_tags))
    ]
    if len(options) == 1:
        return options[0], None
    if not options:
        return None, "no champion unit in the list carries the legend's champion tag"
    return None, (
        "the list legally runs " + " and ".join(options)
        + "; only the pilot knows which sat in the Champion Zone — set chosen_champion by hand"
    )


def save(deck, slug=None, force=False):
    """Write a deck into the gauntlet, refusing to destroy a different one.

    The filename is minted from the deck's name, and names that differ can
    slugify the same — "Rengar Aggro" and "rengar  aggro!!" both become
    `rengar-aggro`. The gauntlet holds committed tournament decklists, so an
    import that silently took a slug already in use replaced real data with no
    warning at all.

    Re-importing under the SAME name overwrites, because that is an update.
    A different name landing on an occupied slug is a collision and is refused.
    """
    import json
    slug = slug or re.sub(r"[^a-z0-9]+", "-", deck["name"].lower()).strip("-") or "deck"
    path = os.path.join(deckfile.GAUNTLET_DIR, f"{slug}.json")

    if os.path.exists(path) and not force:
        try:
            with open(path, encoding="utf-8") as fh:
                existing = json.load(fh)
        except (ValueError, OSError):
            existing = None
        if existing and existing.get("name") != deck["name"]:
            raise ImportError_(
                f"  {slug}.json already holds {existing.get('name')!r}, and "
                f"{deck['name']!r} would overwrite it.\n"
                f"  Pass --slug <name> to file this one elsewhere."
            )

    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(deck, fh, indent=1, ensure_ascii=False)
    return path
