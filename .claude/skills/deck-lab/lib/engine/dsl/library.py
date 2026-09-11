"""The committed scripts, and the two numbers that say how far they go.

Coverage is measured two ways here and neither of them is "cards with a
script". That metric is how the prior C++ Riftbound engine reported near-
complete coverage while its own audit found 325 of 787 cards (41%) with a real
gap, and ADR 0009 decision 3 rules it out by name.

* **Clause coverage** — every clause of every scripted card's printed text is
  marked `implemented`, `approx` or `unsupported`. The denominator is clauses,
  so a card whose script covers three of its four clauses counts as three of
  four rather than as one card.
* **Atom coverage** — which of the census's active atoms at least one script
  exercises. The hand-written set is the DSL's acceptance test (plan §4.3), and
  an atom nothing exercises is a construct nobody has ever written down.

Both are computed from the scripts themselves. Neither is stored, so neither
can go stale.
"""
import json
import os
import re

import cards

from . import schema

HERE = os.path.dirname(os.path.abspath(__file__))
#: lib/engine/dsl -> lib/engine -> lib -> the skill folder
SKILL = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
SCRIPTS_DIR = os.path.join(SKILL, "data", "scripts")

_SLUG_STRIP = re.compile(r"[^a-z0-9]+")


def slug(name):
    """The file a card's script lives in.

    Derived from the card name rather than chosen, so two people scripting the
    same card collide in git rather than shipping two scripts for one card.
    """
    return _SLUG_STRIP.sub("-", (name or "").lower()).strip("-")


def paths(directory=None):
    directory = SCRIPTS_DIR if directory is None else directory
    if not os.path.isdir(directory):
        return []
    return sorted(os.path.join(directory, f) for f in os.listdir(directory)
                  if f.endswith(".json"))


def load(path):
    """One script, or an `unreadable` record in place of it."""
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh), None
    except (OSError, ValueError) as err:
        return None, schema.error("unreadable", os.path.basename(path),
                                  "could not be read as JSON: %s" % err)


def check(path, doc):
    """Validate one script, plus the checks that need its filename."""
    errors = list(schema.validate(doc))
    want = slug(doc.get("card") or "")
    got = os.path.splitext(os.path.basename(path))[0]
    if want and want != got:
        errors.append(schema.error(
            "filename_mismatch", os.path.basename(path),
            "a script for %r belongs in %s.json" % (doc.get("card"), want),
            token=got, expected=(want,)))
    return errors


class Script(object):
    __slots__ = ("path", "doc", "errors")

    def __init__(self, path, doc, errors):
        self.path = path
        self.doc = doc
        self.errors = errors

    @property
    def card(self):
        return (self.doc or {}).get("card") or os.path.basename(self.path)

    @property
    def ok(self):
        return not self.errors

    @property
    def clauses(self):
        return (self.doc or {}).get("clauses") or []

    def marks(self):
        counts = dict((s, 0) for s in schema.CLAUSE_STATUS)
        for clause in self.clauses:
            status = (clause or {}).get("status")
            if status in counts:
                counts[status] += 1
        return counts

    def atoms(self):
        return schema.atoms_of(self.doc) if self.doc else set()


def load_all(directory=None):
    out = []
    for path in paths(directory):
        doc, err = load(path)
        if doc is None:
            out.append(Script(path, None, [err]))
            continue
        out.append(Script(path, doc, check(path, doc)))
    return out


def stamp_all(directory=None):
    """Rewrite every stale `version` from its body. Returns the paths changed.

    A formatter, not a fix: the hash exists so a game log can say which script
    played a card, and this only recomputes it from what is on disk. It cannot
    make a wrong script right, and nothing calls it automatically — a version
    that silently re-stamped itself on read would answer its own question.
    """
    changed = []
    for path in paths(directory):
        doc, err = load(path)
        if doc is None:
            continue
        want = schema.body_hash(doc)
        if doc.get("version") == want:
            continue
        doc["version"] = want
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(doc, fh, indent=1, ensure_ascii=False)
            fh.write("\n")
        changed.append(path)
    return changed


def coverage(scripts=None):
    """The report `deck_cli.py scripts` prints, as data."""
    scripts = load_all() if scripts is None else scripts
    exercised = set()
    marks = dict((s, 0) for s in schema.CLAUSE_STATUS)
    for script in scripts:
        exercised |= script.atoms()
        for status, n in script.marks().items():
            marks[status] += n
    active = schema.active_atoms()
    total_clauses = sum(marks.values())
    return {
        "scripts": len(scripts),
        "valid": sum(1 for s in scripts if s.ok),
        "invalid": sum(1 for s in scripts if not s.ok),
        "errors": sum(len(s.errors) for s in scripts),
        "clauses": total_clauses,
        "marks": marks,
        "clause_coverage": (marks["implemented"] / total_clauses) if total_clauses else 0.0,
        "atoms_active": len(active),
        "atoms_exercised": len(active & exercised),
        "unexercised": sorted(active - exercised),
        #: Atoms a script used that the active set does not contain. Always
        #: empty while the validator is doing its job — printed anyway, because
        #: an instrument that can only report the expected reading is not one.
        "outside": sorted(exercised - active),
    }


def by_card(scripts=None):
    scripts = load_all() if scripts is None else scripts
    out = {}
    for script in scripts:
        name = (script.doc or {}).get("card")
        if name:
            out[cards.find(name)["name"] if cards.find(name) else name] = script
    return out


def readiness(deck, scripts=None):
    """How much of one deck the script library can execute.

    Counted over the deck's DISTINCT cards, legend and Chosen Champion included:
    both are executed every game and neither is shuffled, so leaving them out
    would report a deck as readier than it is.
    """
    import deckfile
    have = set(by_card(scripts))
    names = sorted(deckfile.distinct_cards([deck]))
    scripted = [n for n in names if n in have]
    unscripted = [n for n in names if n not in have]
    return {
        "distinct": len(names),
        "scripted": scripted,
        "unscripted": unscripted,
        "share": (len(scripted) / len(names)) if names else 0.0,
    }
