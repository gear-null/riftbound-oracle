"""Checks for the card-script DSL, run as part of `deck_cli.py selftest`.

Three things are being defended here and they fail in different ways.

**The vocabulary is a measurement.** `docs/engine/vocabulary-census.md` counted
33 effect primitives, 20 trigger events, 25 selector atoms, 17 condition atoms,
4 choice forms, 10 cost forms, 6 replacement kinds and 5 durations at the 95%
line. If the schema drifts from those numbers nothing breaks and every script
still validates — the DSL just stops being the thing that was measured. So the
counts are pinned.

**The validator has to REFUSE.** A schema that accepts everything reports 100%
valid, and the compiler's repair loop then has nothing to repair. Every error
code in `schema.CODES` therefore has a deliberately broken script here and its
record is asserted field by field: code, path, offending token, expected set.
A code no broken script can produce is a code that does not exist.

**Coverage is an instrument, not a score.** Clause arithmetic is checked against
a synthetic library with known marks, so "124 of 137" cannot quietly become
"124 of 124" by dropping the clauses nobody implemented.
"""
import copy
import json
import os

import cards

from . import library, schema

HERE = os.path.dirname(os.path.abspath(__file__))


def _good():
    """A small, complete, valid script, built rather than read.

    Built: the mutation battery runs the suite against a copy of the skill
    folder, and a check that read one of the committed scripts as its fixture
    would still pass there while testing nothing about the file it names.
    """
    doc = {
        "schema": schema.SCHEMA,
        "card": "First Mate",
        "source": "manual",
        "keywords": [],
        "abilities": [
            {"kind": "triggered", "cites": ["CR:382", "CR:383"],
             "trigger": {"events": ["play_self"], "who": "you"},
             "effect": [
                 {"op": "ready", "cites": ["CR:415"],
                  "what": {"type": "unit", "another": True, "side": "any",
                           "targets": True}}]}],
        "clauses": [
            {"text": "When you play me, ready another unit.", "status": "implemented",
             "node": "abilities[0]"}],
        "tests": [
            {"name": "a", "given": {"seats": [{"seat": 0}]},
             "when": {"do": "play", "card": "First Mate", "seat": 0},
             "then": [{"expect": "board_count", "seat": 0, "card": "First Mate", "n": 1}]},
            {"name": "b", "given": {"seats": [{"seat": 0}]},
             "when": {"do": "play", "card": "First Mate", "seat": 0},
             "then": [{"expect": "zone_count", "seat": 0, "zone": "hand", "n": 0}]}],
    }
    return schema.stamp(doc)


def _broken(mutate):
    doc = _good()
    mutate(doc)
    if "version" in doc:
        doc["version"] = schema.body_hash(doc)     # isolate the mutation under test
    return schema.validate(doc)


def _find(errors, code):
    for err in errors:
        if err["code"] == code:
            return err
    return None


# -- the vocabulary is the census's, not this file's ------------------------

def vocabulary(check):
    """The atom counts are the measurement. Drift here is silent otherwise."""
    size = schema.vocabulary_size()
    for label, key, want in (
            ("effect primitives", "primitives", 33),
            ("trigger events", "triggers", 20),
            ("selector atoms", "selectors", 25),
            ("condition atoms", "conditions", 17),
            ("choice forms", "choices", 4),
            ("cost forms", "costs", 10),
            ("replacement kinds", "replacements", 6),
            ("modifier durations", "durations", 5),
    ):
        check(f"the active vocabulary has the {want} {label} the census measured",
              size[key] == want, f"schema says {size[key]}")
    check("all 25 CR keywords are in the table (805-829)", size["keywords"] == 25,
          f"{size['keywords']} keywords")
    check("five keywords take a numeric parameter",
          sum(1 for v in schema.KEYWORDS.values() if v[2]) == 5,
          ", ".join(sorted(k for k, v in schema.KEYWORDS.items() if v[2])))
    check("the ten gauntlet token specs are the ones a script may name",
          size["tokens"] == 10, f"{size['tokens']} with a gauntlet count")

    declared = dict(
        primitives=len(schema.PRIMITIVES), triggers=len(schema.TRIGGERS),
        selectors=len(schema.SELECTORS), conditions=len(schema.CONDITIONS),
        choices=len(schema.CHOICES), costs=len(schema.COSTS),
        replacements=len(schema.REPLACEMENTS), durations=len(schema.DURATIONS))
    for label, key, want in (
            ("primitives", "primitives", 56), ("triggers", "triggers", 39),
            ("selectors", "selectors", 38), ("conditions", "conditions", 23),
            ("choices", "choices", 8), ("costs", "costs", 13),
            ("replacements", "replacements", 9), ("durations", "durations", 6),
    ):
        check(f"every {label[:-1]} atom in the whole 954-card pool is declared ({want})",
              declared[key] == want, f"schema declares {declared[key]}")

    # Two of the CR's 32 game actions are performed constantly and printed never.
    # A primitive list drawn from the chapter heading would not make that split.
    check("burn_out and create are engine actions, not DSL surface",
          set(schema.ENGINE_ONLY) == {"burn_out", "create"}
          and not (set(schema.ENGINE_ONLY) & set(schema.PRIMITIVES)),
          "both are real and neither is written on a card")

    # Every construct has a node type, and every node type has a construct.
    active = set(n for n, a in schema.PRIMITIVES.items() if a.active)
    nodes = set(schema._EFFECTS)
    check("every active primitive is either a node type or carried by a selector",
          active - nodes == {"create_token"},
          f"unhoused: {', '.join(sorted(active - nodes - {'create_token'})) or 'none'}")
    check("no node type exists for an atom the census did not measure",
          not (nodes - active), f"invented: {', '.join(sorted(nodes - active))}")

    # A citation is only worth checking if the table it is checked against is real.
    cited = set()
    for table in (schema.PRIMITIVES, schema.TRIGGERS, schema.SELECTORS,
                  schema.CONDITIONS, schema.CHOICES, schema.COSTS,
                  schema.REPLACEMENTS, schema.DURATIONS):
        cited |= set(a.cite.split(":")[-1] for a in table.values())
    cited |= set(c.split(":")[-1] for c in schema._ABILITY_CITE.values())
    cited |= set(v[0].split(":")[-1] for v in schema.KEYWORDS.values())
    check("every rule the vocabulary names is a section this schema can cite",
          not (cited - set(schema.SECTIONS)),
          f"missing from SECTIONS: {', '.join(sorted(cited - set(schema.SECTIONS)))}")

    check("Mighty is a state at CR 706 and not a 26th keyword",
          "Mighty" not in schema.KEYWORDS and "Mighty" in schema.NOT_KEYWORDS
          and "mighty" in schema.STATES,
          "the corpus sets it in the keyword font on ten cards")


# -- the validator refuses, and says why -------------------------------------

def validator_errors(check):
    """Every error code, from a deliberately broken script, asserted by field."""
    err = _find(_broken(lambda d: d.__setitem__("schema", "riftbound/0")),
                "schema_not_recognised")
    check("an unrecognised schema version is refused before anything else",
          err is not None and err["path"] == "schema"
          and err["token"] == "riftbound/0" and err["expected"] == [schema.SCHEMA],
          json.dumps(err))

    err = _find(_broken(lambda d: d["abilities"][0].pop("trigger")), "missing_field")
    check("a missing required field names the path and the field",
          err is not None and err["path"] == "abilities[0].trigger"
          and "trigger" in err["expected"], json.dumps(err))

    err = _find(_broken(lambda d: d["abilities"][0].__setitem__("colour", "blue")),
                "unexpected_field")
    check("a field the schema does not define is refused, not ignored",
          err is not None and err["path"] == "abilities[0].colour"
          and err["token"] == "colour", json.dumps(err))

    err = _find(_broken(lambda d: d["abilities"][0]["effect"][0].__setitem__(
        "what", "everything")), "wrong_type")
    check("a field of the wrong JSON type is refused with the value shown",
          err is not None and err["path"] == "abilities[0].effect[0].what"
          and "everything" in (err.get("token") or ""), json.dumps(err))

    err = _find(_broken(lambda d: d["abilities"][0]["effect"][0].__setitem__(
        "op", "smite")), "unknown_atom")
    # Asserted against the ATOM table's expected set, not the node table's. A
    # second guard behind this one ("an active atom with no node type") produces
    # the same code, path and token for the same input, so a looser assertion
    # here passes with this one deleted — the masking-pair problem the table's
    # own `guards` section documents. `create_token` is in the atom table and
    # has no node type, so it tells the two apart.
    check("a verb no census table contains is an unknown atom",
          err is not None and err["path"] == "abilities[0].effect[0].op"
          and err["token"] == "smite" and "create_token" in err["expected"],
          json.dumps(err))

    # The distinction this pair draws is the whole point of declaring the tail:
    # `smite` is a typo, `hide` is a real thing cards say that this vocabulary
    # version has not taken on, and a repair loop must not treat them alike.
    err = _find(_broken(lambda d: d["abilities"][0]["effect"][0].__setitem__(
        "op", "hide")), "reserved_atom")
    check("a real census atom outside the active cut is reserved, not unknown",
          err is not None and err["token"] == "hide" and err["cite"] == "CR:421"
          and "3 gauntlet clause" in err["message"], json.dumps(err))

    err = _find(_broken(lambda d: d["abilities"][0]["effect"][0].__setitem__(
        "op", "burn_out")), "engine_only_atom")
    check("a game action no card's text names is refused as engine-only",
          err is not None and err["token"] == "burn_out" and err["cite"] == "CR:431",
          json.dumps(err))

    err = _find(_broken(lambda d: d.__setitem__("keywords", ["Mighty"])),
                "not_a_keyword")
    check("Mighty in a keyword slot is refused and pointed at CR 706",
          err is not None and err["token"] == "Mighty" and err["cite"] == "CR:706",
          json.dumps(err))

    err = _find(_broken(lambda d: d.__setitem__("keywords", ["Rampage"])),
                "unknown_keyword")
    check("a word that is not in the CR glossary is not a keyword",
          err is not None and err["token"] == "Rampage"
          and err["cite"] == "CR:800" and "Deathknell" in err["expected"],
          json.dumps(err))

    err = _find(_broken(lambda d: d["abilities"][0].__setitem__(
        "gate", {"keyword": "Tank"})), "keyword_kind")
    check("only a dependent keyword may gate an ability (135.2.e.7.b)",
          err is not None and err["token"] == "Tank"
          and set(err["expected"]) == {"Empowered", "Legion", "Level"},
          json.dumps(err))

    err = _find(_broken(lambda d: d.__setitem__("keywords", ["Assault"])),
                "keyword_parameter")
    check("a keyword that takes a number cannot be written without one",
          err is not None and err["token"] == "Assault" and err["cite"] == "CR:807",
          json.dumps(err))

    err = _find(_broken(lambda d: d["abilities"][0]["effect"][0].__setitem__(
        "cites", ["415"])), "bad_citation")
    check("a citation that is not CR plus a rule number is malformed",
          err is not None and err["path"] == "abilities[0].effect[0].cites[0]"
          and err["token"] == "415", json.dumps(err))

    err = _find(_broken(lambda d: d["abilities"][0]["effect"][0].__setitem__(
        "cites", ["CR:999"])), "bad_citation")
    check("a citation to a section that does not exist is refused",
          err is not None and err["token"] == "CR:999", json.dumps(err))

    err = _find(_broken(lambda d: d["abilities"][0]["effect"][0].pop("cites")),
                "missing_citation")
    check("a node with no citation is refused, not silently uncited",
          err is not None and err["path"] == "abilities[0].effect[0].cites"
          and err["expected"] == ["CR:415"], json.dumps(err))

    err = _find(_broken(lambda d: d["abilities"][0]["effect"][0].__setitem__(
        "cites", ["CR:413"])), "wrong_citation")
    check("a well-formed citation to the wrong rule is still wrong",
          err is not None and err["expected"] == ["CR:415"]
          and "CR:415" in err["message"], json.dumps(err))

    err = _find(_broken(lambda d: d["abilities"][0]["effect"].append(
        {"op": "modify_cost", "what": {"self": True}, "delta": -2,
         "cites": ["CR:356"]})), "missing_field")
    check("a cost reduction with no floor is refused (the min-clamp)",
          err is not None and err["path"].endswith(".min")
          and err["cite"] == "CR:356", json.dumps(err))

    err = _find(_broken(lambda d: d["abilities"][0]["effect"].append(
        {"op": "add", "cites": ["CR:429"]})), "bad_value")
    check("Add must put exactly one of a Power or a token into play",
          err is not None and set(err["expected"]) == {"power", "token"}
          and err["cite"] == "CR:429", json.dumps(err))

    err = _find(_broken(lambda d: d.__setitem__("card", "Second Mate")),
                "unknown_card")
    check("a script for a card that is not in the pool is refused",
          err is not None and err["path"] == "card" and err["token"] == "Second Mate",
          json.dumps(err))

    err = _find(_broken(lambda d: d["clauses"][0].__setitem__(
        "text", "Draw seventeen cards.")), "clause_not_in_text")
    check("a clause that is not a run of the printed text is refused",
          err is not None and err["path"] == "clauses[0].text"
          and err["token"] == "Draw seventeen cards.", json.dumps(err))

    err = _find(_broken(lambda d: d["clauses"][0].__setitem__("node", "abilities[9]")),
                "bad_clause_ref")
    check("a clause cannot be implemented by a node that is not there",
          err is not None and err["path"] == "clauses[0].node"
          and err["token"] == "abilities[9]", json.dumps(err))

    doc = _good()
    doc["version"] = "sha256:0000000000000000"
    err = _find(schema.validate(doc), "version_stale")
    check("a version that is not the hash of the body is refused",
          err is not None and err["expected"] == [schema.body_hash(doc)],
          json.dumps(err))

    err = _find(_broken(lambda d: d.__setitem__("tests", d["tests"][:1])), "bad_test")
    check("fewer than two scenario tests is refused",
          err is not None and err["path"] == "tests" and err["token"] == "1",
          json.dumps(err))

    err = _find(_broken(lambda d: d["tests"][0].__setitem__("then", [])), "bad_test")
    check("a test with no expectation cannot fail and is refused",
          err is not None and err["path"] == "tests[0].then", json.dumps(err))

    err = _find(_broken(lambda d: d["tests"][0]["when"].__setitem__("do", "vibe")),
                "bad_test")
    check("a test action outside the closed set is refused",
          err is not None and err["path"] == "tests[0].when.do"
          and err["token"] == "vibe", json.dumps(err))

    # CR 355.10 is two pages of exceptions, and the answer differs between two
    # clauses one selector shape apart. The script says which; it is not inferred.
    err = _find(_broken(lambda d: d["abilities"][0]["effect"].append(
        {"choice": "choose_object", "what": {"type": "unit", "side": "friendly"},
         "do": [{"op": "ready", "what": {"ref": "it"}, "cites": ["CR:415"]}]})),
        "missing_field")
    check("a choice must say whether what it chooses is a Target (355.10)",
          err is not None and err["path"].endswith(".targets")
          and err["cite"] == "CR:355", json.dumps(err))

    errs = _broken(lambda d: d["abilities"][0]["trigger"].pop("who"))
    err = _find(errs, "missing_field")
    check("a trigger must say WHO it listens to (383.4.c.2, 383.4.d.2)",
          err is not None and err["path"] == "abilities[0].trigger.who"
          and err["cite"] == "CR:383" and set(err["expected"]) == set(schema.WHO),
          json.dumps(err))

    # filename_mismatch and unreadable belong to the library, not the schema.
    errs = library.check("/tmp/sasquatch.json", _good())
    err = _find(errs, "filename_mismatch")
    check("a script must live in the file named after its card",
          err is not None and err["expected"] == ["first-mate"]
          and err["token"] == "sasquatch", json.dumps(err))

    doc, err = library.load(os.path.join(HERE, "selftest.py"))
    check("a file that is not JSON is reported, not raised",
          doc is None and err is not None and err["code"] == "unreadable",
          json.dumps(err))

    produced = set()
    for mutation in (lambda d: d.__setitem__("schema", "x"),):
        produced.update(e["code"] for e in _broken(mutation))
    check("a valid script produces no errors at all", not schema.validate(_good()),
          json.dumps(schema.validate(_good()))[:120])

    # Every code in the interface has to be reachable. A code nothing can produce
    # is a branch of the repair loop that will never be taken and never tested.
    reached = set()
    for mutate in (
            lambda d: d.__setitem__("schema", "x"),
            lambda d: d["abilities"][0].pop("trigger"),
            lambda d: d["abilities"][0].__setitem__("colour", "blue"),
            lambda d: d["abilities"][0]["effect"][0].__setitem__("what", "all"),
            lambda d: d["abilities"][0]["effect"][0].__setitem__("op", "smite"),
            lambda d: d["abilities"][0]["effect"][0].__setitem__("op", "hide"),
            lambda d: d["abilities"][0]["effect"][0].__setitem__("op", "burn_out"),
            lambda d: d.__setitem__("keywords", ["Mighty"]),
            lambda d: d.__setitem__("keywords", ["Rampage"]),
            lambda d: d["abilities"][0].__setitem__("gate", {"keyword": "Tank"}),
            lambda d: d.__setitem__("keywords", ["Assault"]),
            lambda d: d["abilities"][0]["effect"][0].__setitem__("cites", ["CR:999"]),
            lambda d: d["abilities"][0]["effect"][0].pop("cites"),
            lambda d: d["abilities"][0]["effect"][0].__setitem__("cites", ["CR:413"]),
            lambda d: d["abilities"][0]["effect"].append(
                {"op": "add", "cites": ["CR:429"]}),
            lambda d: d.__setitem__("card", "Second Mate"),
            lambda d: d["clauses"][0].__setitem__("text", "Draw seventeen cards."),
            lambda d: d["clauses"][0].__setitem__("node", "abilities[9]"),
            lambda d: d.__setitem__("tests", d["tests"][:1]),
    ):
        reached.update(e["code"] for e in _broken(mutate))
    doc = _good()
    doc["version"] = "sha256:0"
    reached.update(e["code"] for e in schema.validate(doc))
    reached.update(e["code"] for e in library.check("/tmp/x.json", _good()))
    reached.add("unreadable")
    missing = set(schema.CODES) - reached
    check("every error code the interface declares can actually be produced",
          not missing, f"unreachable: {', '.join(sorted(missing))}")


# -- the committed library ---------------------------------------------------

def script_library(check):
    scripts = library.load_all()
    check("there are at least 40 hand-written scripts", len(scripts) >= 40,
          f"{len(scripts)} in data/scripts")
    bad = [(s.card, s.errors[0]["code"], s.errors[0]["path"]) for s in scripts if not s.ok]
    check("every committed script validates against the schema", not bad,
          "; ".join(f"{c}: {code} at {p}" for c, code, p in bad[:4]) or
          f"{len(scripts)} scripts")
    check("every committed script is hand-written and says so",
          all((s.doc or {}).get("source") == "manual" for s in scripts),
          "the compiler's output will say `compiled`")

    # The hand-written set is the DSL's acceptance test, the compiler's few-shot
    # corpus and its retrieval index, so it has to span the card types rather
    # than 66 units.
    kinds = {}
    for script in scripts:
        card = cards.find(script.card)
        if card:
            kinds[card["stats"]["type"]] = kinds.get(card["stats"]["type"], 0) + 1
    for kind in ("Unit", "Spell", "Gear", "Battlefield", "Legend"):
        check(f"the library covers at least one {kind}", kinds.get(kind, 0) > 0,
              f"{kinds.get(kind, 0)} of {len(scripts)}")
    check("the library covers champions and multi-trigger cards",
          sum(1 for s in scripts
              if (cards.find(s.card) or {}).get("stats", {}).get("supertype") == "Champion") > 0
          and sum(1 for s in scripts if len(s.doc.get("abilities") or []) > 1) >= 5,
          "several abilities per card is the shape the prior engine's audit flagged")

    every = set()
    for script in scripts:
        slug = library.slug(script.card)
        check_name = slug in every
        every.add(slug)
        if check_name:
            check(f"two scripts claim the same card ({script.card})", False)
    check("no two scripts claim the same card", len(every) == len(scripts),
          f"{len(every)} distinct cards")


def atom_coverage(check):
    """Which measured atoms the hand-written set actually exercises.

    An atom nothing exercises is a construct nobody has ever written down. The
    one unreached atom is named rather than rounded away: `condition:empty`
    appears once in the whole gauntlet, on Hallowed Tomb, and that card also
    needs `zone:champion` and `type:champion`, both reserved. The 95% cut is not
    closed under composition, and this is where that shows.
    """
    cov = library.coverage()
    unreachable = {"condition:empty"}
    missing = set(cov["unexercised"]) - unreachable
    check("every active census atom is exercised by at least one script",
          not missing, f"unexercised: {', '.join(sorted(missing))}")
    check("the atoms that cannot be reached are named, not rounded away",
          set(cov["unexercised"]) == unreachable,
          f"expected exactly {sorted(unreachable)}, got {cov['unexercised']}")
    check("no script exercises an atom outside the active vocabulary",
          not cov["outside"], ", ".join(cov["outside"]))
    # The headline and the list are two readings of one measurement, and the way
    # a coverage number goes wrong is by drifting from the list underneath it.
    check("the coverage report counts against the vocabulary, not against itself",
          cov["atoms_active"] == len(schema.active_atoms())
          and cov["atoms_exercised"] == cov["atoms_active"] - len(cov["unexercised"]),
          f"{cov['atoms_exercised']}/{cov['atoms_active']} with "
          f"{len(cov['unexercised'])} listed as unexercised")


def clause_coverage(check):
    """The arithmetic, against a library whose marks are known.

    Read from a synthetic set rather than from disk: a check that asserted the
    real numbers would have to be edited every time a script is added, and the
    thing worth defending is that `implemented / total` counts the clauses
    NOBODY implemented in its denominator.
    """
    def fake(implemented, approx, unsupported):
        doc = _good()
        doc["clauses"] = (
            [{"text": "When you play me, ready another unit.", "status": "implemented",
              "node": "abilities[0]"}] * implemented
            + [{"text": "ready another unit", "status": "approx", "reason": "r"}] * approx
            + [{"text": "ready another", "status": "unsupported", "reason": "r"}] * unsupported)
        return library.Script("/tmp/fake.json", doc, [])

    cov = library.coverage([fake(3, 1, 1), fake(1, 0, 0)])
    check("clause coverage counts every clause, implemented or not",
          cov["clauses"] == 6 and cov["marks"]["implemented"] == 4, json.dumps(cov["marks"]))
    check("an unsupported clause LOWERS coverage rather than vanishing from it",
          abs(cov["clause_coverage"] - 4.0 / 6.0) < 1e-9,
          f"{cov['clause_coverage']:.4f}")
    better = library.coverage([fake(3, 1, 1)])
    worse = library.coverage([fake(3, 1, 1), fake(0, 0, 2)])
    check("adding a card nobody implemented moves the number down",
          worse["clause_coverage"] < better["clause_coverage"],
          f"{better['clause_coverage']:.2f} -> {worse['clause_coverage']:.2f}")
    check("an empty library reports zero coverage rather than dividing by zero",
          library.coverage([])["clause_coverage"] == 0.0)

    # The instrument has to be able to register a bad reading. `scripts` is what
    # a reader looks at, so a broken script must show up there as broken.
    broken = library.Script("/tmp/b.json", _good(),
                            [schema.error("wrong_type", "x", "y")])
    check("an invalid script is counted as invalid by the report",
          library.coverage([broken])["invalid"] == 1)

    marks = library.coverage()["marks"]
    check("every committed clause carries one of the three marks",
          sum(marks.values()) == sum(len(s.clauses) for s in library.load_all()),
          json.dumps(marks))
    for status in ("approx", "unsupported"):
        reasoned = all(c.get("reason") for s in library.load_all() for c in s.clauses
                       if c.get("status") == status)
        check(f"every {status} clause in the library says why", reasoned,
              "a mark with no reason is a shrug")


def version_hashing(check):
    """What the hash covers, and what it deliberately does not."""
    doc = _good()
    check("a stamped script's version is the hash of its body",
          doc["version"] == schema.body_hash(doc), doc["version"])
    check("the hash is stable across two runs of the same body",
          schema.body_hash(_good()) == schema.body_hash(_good()))

    changed = _good()
    changed["abilities"][0]["effect"][0]["what"]["side"] = "friendly"
    check("changing what a card DOES changes its version",
          schema.body_hash(changed) != doc["version"],
          "a log quoting the old hash would name a script that no longer exists")

    same = _good()
    same["tests"][0]["name"] = "a completely different name"
    same["clauses"][0]["status"] = "approx"
    same["clauses"][0]["reason"] = "r"
    same["notes"] = "written later"
    check("editing tests, coverage marks or notes does NOT change the version",
          schema.body_hash(same) == doc["version"],
          "the hash answers 'was this game played with this script', nothing else")

    reordered = _good()
    reordered["abilities"][0] = dict(
        reversed(list(reordered["abilities"][0].items())))
    check("key order in the JSON does not change the version",
          schema.body_hash(reordered) == doc["version"])

    stale = [s.card for s in library.load_all()
             if (s.doc or {}).get("version") != schema.body_hash(s.doc or {})]
    check("every committed script's version matches its body", not stale,
          ", ".join(stale[:5]))


def readiness(check):
    """`check <deck>` reports what can be PLAYED, not what is legal."""
    import deckfile
    deck = deckfile.resolve("irelia-core-meta")
    ready = library.readiness(deck)
    names = set(deckfile.distinct_cards([deck]))
    check("readiness is measured over the deck's distinct cards",
          ready["distinct"] == len(names), f"{ready['distinct']} vs {len(names)}")
    check("the legend and the Chosen Champion are inside the count",
          deck.legend in names and deck.chosen_champion in names,
          "neither is shuffled and both are executed every game")
    check("scripted and unscripted partition the deck exactly",
          sorted(ready["scripted"] + ready["unscripted"]) == sorted(names)
          and not (set(ready["scripted"]) & set(ready["unscripted"])),
          f"{len(ready['scripted'])} + {len(ready['unscripted'])}")
    check("a deck with no scripted card reports zero rather than crashing",
          library.readiness(deck, [])["share"] == 0.0)


def clause_text(check):
    """Coverage marks are checked against the corpus, not trusted."""
    printed = ("[Assault 2] (+2 :rb_might: while I'm an attacker.) "
               "When you play me, discard 1.")
    check("a clause quoting the printed text is accepted",
          schema.quotes_printed_text("When you play me, discard 1.", printed))
    check("a clause that is only a keyword falls back to the bracketed form",
          schema.quotes_printed_text("[Assault 2]", printed),
          "nothing survives normalisation, so the literal form is compared")
    check("reminder text is not a clause a script may claim",
          not schema.quotes_printed_text("while I'm an attacker", printed),
          "CR 135.2.d.3: its presence and wording have no effect on game function")
    check("text the card does not print is refused",
          not schema.quotes_printed_text("When you play me, draw 1.", printed))
    check("the two symbol notations compare equal",
          schema.words("pay :rb_energy_1::rb_rune_chaos:") == schema.words("pay [1][P]"),
          "Riftcodex and Riot's errata articles write one cost two ways")
    check("an empty clause is not a run of anything",
          not schema.quotes_printed_text("", printed))


SECTIONS = (vocabulary, validator_errors, script_library, atom_coverage,
            clause_coverage, version_hashing, readiness, clause_text)
