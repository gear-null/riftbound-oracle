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

    **Canonicalised first.** The corpus spells a subtitled card two ways —
    Riftcodex writes `Irelia - Fervent`, decklist sites write `Irelia, Fervent`
    — and both forms appear in the committed gauntlet. Slugging the raw string
    turns one card into two files (`irelia-fervent` from both, as it happens,
    but `Dr. Mundo - Expert` and `Dr. Mundo, Expert` do not collide), so a deck
    naming the other form reported the card unscripted while its script sat
    right there. `cards.find` already resolves both spellings to one record;
    this asks it, and falls back to the raw string only for a name the pool does
    not know — which `validate` refuses anyway.
    """
    # Total, for any input. `check()` calls this on whatever `card` a hostile
    # document carries, and `cards.find(["not", "a", "name"])` raises inside the
    # corpus's own regex — which took the whole library down with it, one file at
    # a time. A name that is not a string names no card.
    if not isinstance(name, str):
        return ""
    card = cards.find(name)
    return _SLUG_STRIP.sub("-", ((card["name"] if card else name) or "").lower()).strip("-")


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
    """Validate one script, plus the checks that need its filename.

    Isolated: one unreadable or hostile file must be one bad row in the report,
    not an exception that takes the other sixty-six down with it. `validate`
    already promises never to raise; this is the second half of that promise,
    for the filename checks and for anything the document does to `.get`.
    """
    try:
        return _check(path, doc)
    except Exception as err:                                    # noqa: BLE001
        return [schema.error("internal_error", os.path.basename(path),
                             "checking this script raised: %s: %s"
                             % (type(err).__name__, err))]


def _check(path, doc):
    errors = list(schema.validate(doc))
    want = slug(doc.get("card") or "") if isinstance(doc, dict) else ""
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
    done = words = 0
    for script in scripts:
        exercised |= script.atoms()
        for status, n in script.marks().items():
            marks[status] += n
        a, b = clause_words(script)
        done += a
        words += b
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
        "words": words,
        "words_implemented": done,
        "word_coverage": (done / words) if words else 0.0,
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


def clause_words(script):
    """(implemented words, total words) for one script's clauses.

    The second number the coverage line carries, and the one that cannot be
    gamed by splitting: a clause cut into three has the same words as the clause
    it came from, where it has three times the clause count. With the partition
    rule underneath it — the clauses' words ARE the card's words — this is
    coverage of the printed text rather than of a denominator the script chose.
    """
    done = total = 0
    for clause in script.clauses:
        if not isinstance(clause, dict):
            continue
        n = len(schema.words(clause.get("text") or ""))
        total += n
        if clause.get("status") == "implemented":
            done += n
    return done, total


def splitter_counts():
    """The census splitter's clause count per card, as vendored.

    `engine-train/census.py` cannot be imported from inside the skill (ADR
    0004), so its number is vendored beside the scripts and regenerated when the
    corpus or the splitter changes. It is a BOUND, not an equality: the splitter
    cuts a sentence into its trigger condition, its gating conditions and its
    instructions, where a clause here is the readable span a person marks. The
    splitter is therefore finer on 56 of 67 cards and never coarser, and a
    script that claims more clauses than the splitter found has split its own
    text to move the ratio.
    """
    path = os.path.join(SKILL, "data", "clause-counts.json")
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh).get("counts") or {}
    except (OSError, ValueError):
        return {}


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
