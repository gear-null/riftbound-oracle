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
a synthetic library with known marks, so "136 of 138" cannot quietly become
"136 of 136" by dropping the clauses nobody implemented.
"""
import copy
import json
import os
import random

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


def _good_many():
    """A valid script with FOUR clauses, of three different kinds.

    `_good()` has one, and a one-clause fixture cannot tell "every clause is
    validated" from "the first clause is validated" — truncating the clause loop
    to `clauses[:1]` left the whole suite green. This fixture is Back Off, whose
    printed text really does split four ways, and the checks below put the
    defect in the LAST clause on purpose.
    """
    doc = {
        "schema": schema.SCHEMA,
        "card": "Back Off",
        "source": "manual",
        "keywords": [{"keyword": "Hidden", "cites": ["CR:811"]},
                     {"keyword": "Action", "cites": ["CR:806"]}],
        "abilities": [
            {"kind": "passive", "cites": ["CR:363"],
             "effect": [
                 {"op": "stun", "cites": ["CR:423"],
                  "what": {"type": "unit", "side": "any", "targets": True}},
                 {"op": "draw", "n": 1, "seat": "you", "cites": ["CR:413"],
                  "when": {"cond": "played_from", "zone": "hand",
                           "what": {"self": True}}}]}],
        "clauses": [
            {"text": "[Hidden]", "status": "implemented", "node": "keywords[0]"},
            {"text": "[Action]", "status": "implemented", "node": "keywords[1]"},
            {"text": "[Stun] a unit.", "status": "implemented",
             "node": "abilities[0].effect[0]"},
            {"text": "If you played this from your hand, draw 1.",
             "status": "implemented", "node": "abilities[0].effect[1]"}],
        "tests": [
            {"name": "a", "given": {"seats": [{"seat": 0}]},
             "when": {"do": "play", "card": "Back Off", "seat": 0},
             "then": [{"expect": "chain", "n": 0}]},
            {"name": "b", "given": {"seats": [{"seat": 0}]},
             "when": {"do": "play", "card": "Back Off", "seat": 0},
             "then": [{"expect": "zone_count", "seat": 0, "zone": "hand", "n": 0}]}],
    }
    return schema.stamp(doc)


def _broken_many(mutate):
    doc = _good_many()
    mutate(doc)
    doc["version"] = schema.body_hash(doc)
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
    promoted = {}
    for key in schema.PROMOTED:
        promoted[key.split(":", 1)[0]] = promoted.get(key.split(":", 1)[0], 0) + 1
    for label, key, category in (
            ("effect primitives", "primitives", "primitive"),
            ("trigger events", "triggers", "trigger"),
            ("selector atoms", "selectors", "selector"),
            ("condition atoms", "conditions", "condition"),
            ("choice forms", "choices", "choice"),
            ("cost forms", "costs", "cost"),
            ("replacement kinds", "replacements", "replacement"),
            ("modifier durations", "durations", "duration"),
    ):
        cut = schema.CENSUS_95[category]
        want = cut + promoted.get(category, 0)
        check(f"the active {label} are the census's {cut} plus its promotions",
              size[key] == want,
              f"schema says {size[key]}, census cut {cut} + "
              f"{promoted.get(category, 0)} promoted")

    # The promotions are the part a reader has to be able to audit: each one is
    # an atom outside the measured cut, and the reason is what stops the list
    # becoming somewhere a vocabulary quietly grows.
    unreasoned = [k for k, v in schema.PROMOTED.items() if not (v or "").strip()]
    check("every promoted atom says which active construct needed it",
          not unreasoned, ", ".join(unreasoned))
    strays = [k for k in schema.PROMOTED
              if k.split(":", 1)[1] not in schema.TABLES[k.split(":", 1)[0]]]
    check("every promoted atom is a real census atom, not an invention",
          not strays, ", ".join(strays))
    inactive = [k for k in schema.PROMOTED
                if not schema.TABLES[k.split(":", 1)[0]][k.split(":", 1)[1]].active]
    check("every promoted atom is actually active", not inactive,
          ", ".join(inactive))
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


def vocabulary_closure(check):
    """Is the active vocabulary closed under composition?

    The census took its 95% cut per table — the 33 commonest primitives, the 25
    commonest selectors — each ranked on its own. Nothing made those lists agree,
    so the cut arrived with holes: `look_at` made it and the top of the deck it
    looks at did not; `[Empower]` and `[Equip]` made it and the game actions they
    perform did not. A clause then reads `approx` for a reason that is an
    artefact of where the line was drawn rather than of anything a card does,
    which is a coverage number measuring the wrong thing.

    Closure is checked two ways, because there are two ways to leave a hole.

    1. **Nothing writable is reserved.** Every value a script may put in a `zone`,
       `at`, `type` or `side` field is an active atom. A reserved one reachable
       through an enum is a hole a compiler falls into at the moment it tries to
       say something true.
    2. **Nothing composed is reserved.** Every atom an active construct reaches
       through another construct — `COMPOSED`, and the ability-kind table — is
       active too.
    """
    holes = []
    for field, prefix in (("zone", "zone:"), ("location", "at:"),
                          ("type", "type:"), ("side", "side:")):
        for value in schema._ENUMS[field]:
            name = prefix + str(value)
            atom = schema.SELECTORS.get(name)
            if atom is None:
                holes.append("%s (no such atom)" % name)
            elif not atom.active:
                holes.append("%s (reserved)" % name)
    check("every value a script may write is an active atom", not holes,
          "; ".join(holes))

    composed = []
    for key, edges in schema.COMPOSED.items():
        for category, atom in edges:
            row = schema.TABLES[category].get(atom)
            if row is None or not row.active:
                composed.append("%s -> %s:%s" % (key, category, atom))
    for kind, edges in schema._ABILITY_ATOMS.items():
        for category, atom in edges:
            row = schema.TABLES[category].get(atom)
            if row is None or not row.active:
                composed.append("ability %s -> %s:%s" % (kind, category, atom))
    check("every atom an active construct composes with is active too",
          not composed, "; ".join(composed))

    # The keyword tables are constructs too: a triggered keyword whose event is
    # reserved is a keyword the schema accepts and no script can implement.
    kw = []
    for name, events in schema.KEYWORD_TRIGGERS.items():
        for event in events:
            row = schema.TRIGGERS.get(event)
            if row is None or not row.active:
                kw.append("[%s] -> trigger:%s" % (name, event))
    check("every event a keyword triggers on is active", not kw, "; ".join(kw))

    # And the shipped scripts: no clause may still be blaming a reserved atom.
    # This is the reading that matters to a reader of the coverage number — the
    # other two are how the schema stops it happening again.
    reserved = set()
    for category, table in schema.TABLES.items():
        for name, atom in table.items():
            if not atom.active:
                reserved.add(name)
    blamed = []
    for script in library.load_all():
        for clause in script.clauses:
            reason = clause.get("reason") or ""
            for name in sorted(reserved):
                if "`%s`" % name in reason:
                    blamed.append("%s: %s" % (script.card, name))
    check("no clause is unimplemented for want of a reserved atom", not blamed,
          "; ".join(blamed[:6]))

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

    check("a valid script produces no errors at all", not schema.validate(_good()),
          json.dumps(schema.validate(_good()))[:120])

    # -- the holes a first pass leaves -----------------------------------
    err = _find(_broken(lambda d: d["abilities"][0]["effect"][0]["what"].update(
        {"self": True, "side": "enemy", "at": "base", "zone": "trash"})),
        "contradictory_selector")
    check("a selector that contradicts itself is refused, not narrowed to nothing",
          err is not None and err["cite"] == "CR:355"
          and err["token"] in ("self+side", "at+zone"), json.dumps(err))

    err = _find(_broken(lambda d: d["abilities"].append(dict(d["abilities"][0]))),
                "duplicate_id")
    check("two abilities cannot claim one id", err is None,
          "no ids in the fixture, so the positive case is below")
    doubled = _good()
    doubled["abilities"][0]["id"] = "a"
    doubled["abilities"].append(dict(doubled["abilities"][0]))
    doubled["version"] = schema.body_hash(doubled)
    err = _find(schema.validate(doubled), "duplicate_id")
    check("an id claimed by two abilities is refused",
          err is not None and err["token"] == "a", json.dumps(err))

    err = _find(_broken(lambda d: d["abilities"][0]["effect"][0].__setitem__(
        "what", {"ref": "nobody"})), "unknown_ref")
    check("a `ref` to a bind nothing establishes is refused",
          err is not None and err["token"] == "nobody", json.dumps(err))

    err = _find(_broken(lambda d: d["abilities"][0]["effect"].append(
        {"op": "draw", "n": -2, "seat": "you", "cites": ["CR:413"]})), "bad_value")
    check("a negative draw is refused", err is not None and err["path"].endswith(".n"),
          json.dumps(err))

    err = _find(_broken(lambda d: d["abilities"][0]["effect"].append(
        {"op": "give_might", "n": -2, "until": "this_turn", "cites": ["CR:477"],
         "what": {"self": True}})), "missing_field")
    check("a negative Might modifier with no floor is refused, not only a cost one",
          err is not None and err["path"].endswith(".min")
          and err["cite"] == "CR:356", json.dumps(err))

    err = _find(_broken(lambda d: d["abilities"][0]["effect"][0]["what"].update(
        {"all": True, "targets": True})), "bad_value")
    check("`all` and `targets` cannot both hold (CR 355.10)",
          err is not None and err["cite"] == "CR:355", json.dumps(err))

    err = _find(_broken(lambda d: d["abilities"][0]["effect"][0]["what"].update(
        {"zone": "hand", "targets": True})), "bad_value")
    check("an object in a non-public zone is not a Target (CR 128)",
          err is not None and err["token"] == "hand", json.dumps(err))

    err = _find(_broken(lambda d: d.__setitem__("keywords", ["Assault"])),
                "keyword_parameter")
    check("a keyword-parameter record carries the set it should have come from",
          err is not None and err.get("expected") and "Tank" in err["expected"],
          json.dumps(err))

    sel = {"self": True}
    for _ in range(400):
        sel = {"not": sel}
    deep = _good()
    deep["abilities"][0]["effect"][0]["what"] = sel
    deep["version"] = schema.body_hash(deep)
    err = _find(schema.validate(deep), "too_deep")
    check("a nest past the walker's limit is a record, not a RecursionError",
          err is not None, json.dumps(err))

    class _Hostile(dict):
        def get(self, *a, **kw):
            raise RuntimeError("a document that fights back")

    err = _find(schema.validate(_Hostile(schema=schema.SCHEMA)), "internal_error")
    check("even a document that fights back returns a record",
          err is not None and "RuntimeError" in err["message"], json.dumps(err))

    err = _find(schema.validate({"schema": schema.SCHEMA, "card": "First Mate",
                                 "source": "manual", "abilities": [], "tests": [],
                                 "clauses": [{"text": "Draw seventeen cards.",
                                              "status": "implemented",
                                              "node": "keywords[0]"}]}),
                "clauses_not_a_partition")
    check("clauses that do not reconstruct the card are refused",
          err is not None and err["path"] == "clauses", json.dumps(err))

    # -- one home per fact -------------------------------------------------
    err = _find(_broken(lambda d: d["abilities"][0]["trigger"].__setitem__(
        "frequency", {"nth": 1, "per": "turn"})), "unexpected_field")
    check("a frequency inside a trigger is refused, and told where it belongs",
          err is not None and err["path"] == "abilities[0].trigger.frequency"
          and err["cite"] == "CR:383" and err["expected"] == ["frequency"],
          json.dumps(err))
    ok = _good()
    ok["abilities"][0]["frequency"] = {"nth": 1, "per": "turn"}
    ok["version"] = schema.body_hash(ok)
    check("and the same frequency on the ABILITY is accepted",
          not schema.validate(ok),
          json.dumps(schema.validate(ok))[:120])

    err = _find(_broken(lambda d: d["abilities"][0]["trigger"].__setitem__(
        "events", ["delayed_next"])), "unknown_atom")
    check("a trigger cannot listen for `delayed_next` — it is a window, not an event",
          err is not None and err["token"] == "delayed_next"
          and err["expected"] == ["delayed"] and err["cite"] == "CR:389",
          json.dumps(err))
    for name in ("nth_time", "frequency_only"):
        err = _find(_broken(lambda d, n=name: d["abilities"][0]["trigger"].__setitem__(
            "events", [n])), "unknown_atom")
        check(f"nor for `{name}`, which is a frequency",
              err is not None and err["expected"] == ["frequency"], json.dumps(err))

    delayed = _good()
    delayed["abilities"][0] = {
        "kind": "delayed", "cites": ["CR:389"], "until": "play_other", "who": "you",
        "window": "this_turn", "frequency": {"nth": 1, "per": "turn"},
        "what": {"type": "unit", "side": "friendly", "bind": "next"},
        "effect": [{"op": "ready", "what": {"ref": "next"}, "cites": ["CR:415"]}]}
    delayed["clauses"] = [{"text": "When you play me, ready another unit.",
                           "status": "implemented", "node": "abilities[0]"}]
    delayed["version"] = schema.body_hash(delayed)
    check("a delayed ability says what it waits FOR, and validates",
          not schema.validate(delayed),
          json.dumps(schema.validate(delayed))[:160])
    check("and it is what credits the census's `delayed_next`",
          "trigger:delayed_next" in schema.atoms_of(delayed),
          ", ".join(sorted(a for a in schema.atoms_of(delayed) if "trigger" in a)))

    # CR 396: a Linked Ability is a SET of abilities that reference each other,
    # not a kind of ability. Modelling it as a kind would make every card with
    # two abilities ambiguous about which one it is.
    check("`linked` is not an ability kind (CR 393-396)",
          "linked" not in schema._ABILITIES,
          "linkage is a relation between abilities, not one of them")

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
    for mutate in (
            lambda d: d["abilities"][0]["effect"][0]["what"].update(
                {"self": True, "side": "enemy"}),
            lambda d: d["abilities"][0]["effect"][0].__setitem__(
                "what", {"ref": "nobody"}),
            lambda d: d["clauses"].append(
                {"text": "[Stun] a unit.", "status": "implemented",
                 "node": "abilities[0]"}),
    ):
        reached.update(e["code"] for e in _broken(mutate))
    reached.update(e["code"] for e in schema.validate(doubled))
    reached.update(e["code"] for e in schema.validate(deep))
    reached.update(e["code"] for e in schema.validate(_Hostile(schema=schema.SCHEMA)))
    missing = set(schema.CODES) - reached
    check("every error code the interface declares can actually be produced",
          not missing, f"unreachable: {', '.join(sorted(missing))}")


# -- the committed library ---------------------------------------------------

def hostile_input(check):
    """`validate` returns records for ANY JSON value. Never raises.

    That is the contract the compiler's repair loop is written against, and it
    is not a small one: a walker that raises on `{"op": ["ready"]}` hands the
    loop a traceback it cannot repair from, and one such file in `data/scripts/`
    took `library.load_all` down for all sixty-seven. The first run of this
    check found 3,570 raising inputs across fourteen sites — every one of them a
    table lookup, an iteration or a comparison against a value the schema had
    assumed was a string.

    Deterministic: same seed, same corpus, same inputs every run.
    """
    def spots(node, prefix=""):
        if isinstance(node, dict):
            for k in list(node):
                yield node, k, "%s.%s" % (prefix, k)
                for row in spots(node[k], "%s.%s" % (prefix, k)):
                    yield row
        elif isinstance(node, list):
            for i in range(len(node)):
                yield node, i, "%s[%d]" % (prefix, i)
                for row in spots(node[i], "%s[%d]" % (prefix, i)):
                    yield row

    values = [None, True, 0, -1, 3.5, "", "x", [], {}, ["abilities[0]"],
              {"a": 1}, [[[]]], {"k": {"k": 1}}]
    rng = random.Random(20260911)
    docs = [s.doc for s in library.load_all() if s.doc][:12]
    raised = []
    backstopped = []
    tried = 0
    for doc in docs:
        places = [p for _, _, p in spots(doc)]
        for path in rng.sample(places, min(len(places), 60)):
            for value in values:
                mutant = copy.deepcopy(doc)
                for container, key, here in spots(mutant):
                    if here == path:
                        container[key] = copy.deepcopy(value)
                        break
                tried += 1
                try:
                    records = schema.validate(mutant)
                except Exception as err:                        # noqa: BLE001
                    raised.append("%s at %s: %s" % (type(err).__name__, path, value))
                    continue
                if any(r["code"] == "internal_error" for r in records):
                    backstopped.append("%s = %r" % (path, value))
    # ONE check, because the property is one: every hostile input is reported by
    # a check that knows what is wrong with it. Splitting it in two made each
    # half unprovable — a missing guard raises, the backstop catches the raise,
    # and "nothing raised" stays green while "nothing was backstopped" reddens,
    # so neither mutant could name the half it proved.
    check("every hostile input is handled by a named check, not by a raise or the backstop",
          not raised and not backstopped,
          f"{tried} inputs; "
          + (f"{len(raised)} raised, e.g. {raised[0]}" if raised else "none raised")
          + "; "
          + (f"{len(backstopped)} reached the backstop, e.g. {backstopped[0]}"
             if backstopped else "none reached the backstop"))

    # A token spec means two things by position, and the coverage number depends
    # on telling them apart: `play a Recruit token` makes one, `another
    # non-Recruit unit` names a kind and makes nothing. Crediting the filter
    # would have a script report token creation it does not do.
    filtering = _good()
    filtering["abilities"] = [
        {"kind": "passive", "cites": ["CR:363"],
         "effect": [{"op": "ready", "cites": ["CR:415"],
                     "what": {"type": "unit", "side": "friendly",
                              "token": {"name": "Recruit", "type": "unit"}}}]}]
    atoms = schema.atoms_of(filtering)
    check("a token spec used as a FILTER does not credit token creation",
          "primitive:create_token" not in atoms and "token:Recruit" in atoms,
          ", ".join(sorted(a for a in atoms if "token" in a)) or "none")

    creating = _good()
    creating["abilities"] = [
        {"kind": "passive", "cites": ["CR:363"],
         "effect": [{"op": "play", "to": "base", "cites": ["CR:419", "CR:179"],
                     "what": {"token": {"name": "Recruit", "type": "unit",
                                        "might": 1}}}]}]
    check("and used in a CREATING position it does",
          "primitive:create_token" in schema.atoms_of(creating))

    # Depth: JSON has no cycles but a hand-built dict does, and either way the
    # stack is finite.
    sel = {"self": True}
    for _ in range(400):
        sel = {"not": sel}
    deep = _good()
    deep["abilities"] = [{"kind": "passive", "cites": ["CR:363"],
                          "effect": [{"op": "ready", "what": sel,
                                      "cites": ["CR:415"]}]}]
    try:
        records = schema.validate(deep)
        ok = any(r["code"] == "too_deep" for r in records)
    except Exception:                                           # noqa: BLE001
        ok = False
    check("400 nested selectors are reported as too deep, not raised", ok)

    # And the library isolates one bad file rather than losing the other sixty-six.
    good = library.load_all()
    poisoned = library.check("/tmp/x.json", {"schema": schema.SCHEMA,
                                             "card": ["not", "a", "name"]})
    # Not merely "a list came back": a list of `internal_error` is what the
    # backstop returns when something raised, and the point is that nothing did.
    # Every row has to be a check that knew what was wrong.
    check("a hostile script is one bad row, not an exception",
          isinstance(poisoned, list) and poisoned
          and all(isinstance(r, dict) for r in poisoned)
          and not any(r["code"] == "internal_error" for r in poisoned),
          json.dumps([r["code"] for r in poisoned]))
    check("and the rest of the library still loads", len(good) >= 40,
          f"{len(good)} scripts")

def script_library(check):
    scripts = library.load_all()
    check("there are at least 40 hand-written scripts", len(scripts) >= 40,
          f"{len(scripts)} in data/scripts")
    bad = [(s.card, s.errors[0]["code"], s.errors[0]["path"]) for s in scripts if not s.ok]
    check("every committed script validates against the schema", not bad,
          "; ".join(f"{c}: {code} at {p}" for c, code, p in bad[:4]) or
          f"{len(scripts)} scripts")
    # A positive control. "No script has an error" is also what a validator that
    # returns nothing says, and that validator would pass every check in this
    # section. So: something the library MUST reject.
    control = library.check("/tmp/nope.json",
                            {"schema": schema.SCHEMA, "card": "First Mate",
                             "source": "manual", "abilities": [{"kind": "wrong"}],
                             "clauses": [], "tests": [], "version": "sha256:0"})
    check("the library reports a script that is wrong, so a clean run means something",
          len(control) >= 3 and any(e["code"] == "unknown_atom" for e in control),
          json.dumps([e["code"] for e in control]))

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

    An atom nothing exercises is a construct nobody has ever written down, so
    this reads zero-tolerance: every active atom, exercised, by name.

    It did not start that way. `condition:empty` sat unreachable for a while —
    one occurrence in the whole gauntlet, on Hallowed Tomb, a card that also
    needs `zone:champion` and `type:champion`, both of which the 95% cut had left
    outside. An active atom stranded on a card whose other atoms are reserved is
    what a cut taken per table does, and closing the vocabulary under composition
    is what let the card be written and the atom be reached.
    """
    cov = library.coverage()
    missing = set(cov["unexercised"])
    check("every active census atom is exercised by at least one script",
          not missing, f"unexercised: {', '.join(sorted(missing))}")
    check("the coverage report lists an unexercised atom rather than rounding it away",
          "unexercised" in cov and isinstance(cov["unexercised"], list),
          "the list is the instrument; the percentage is the headline")
    check("no script exercises an atom outside the active vocabulary",
          not cov["outside"], ", ".join(cov["outside"]))
    # The headline and the list are two readings of one measurement, and the way
    # a coverage number goes wrong is by drifting from the list underneath it.
    # Counted from the tables rather than from `active_atoms()`, which is the
    # function under test: comparing a function to itself is a check that a
    # constant is equal to itself.
    independent = sum(len([1 for a in table.values() if a.active])
                      for table in schema.TABLES.values())
    independent += len(schema.KEYWORDS)
    independent += sum(1 for spec in schema.TOKENS.values() if spec[1])
    independent += 2                                   # for_each, keyword_gate
    check("the coverage report counts against the vocabulary, not against itself",
          cov["atoms_active"] == independent
          and cov["atoms_exercised"] == cov["atoms_active"] - len(cov["unexercised"]),
          f"{cov['atoms_exercised']}/{cov['atoms_active']}, tables say {independent}, "
          f"{len(cov['unexercised'])} listed as unexercised")
    # The whole library exercises everything, so "exercised == active" is true
    # there whether the number is measured or asserted. One script is the case
    # that tells them apart.
    one = library.load_all()[0]
    small = library.coverage([one])
    reached = one.atoms() & schema.active_atoms()
    check("a library of one script reports only the atoms that one script reaches",
          small["atoms_exercised"] == len(reached) < small["atoms_active"],
          f"{small['atoms_exercised']} reported, {len(reached)} reached, "
          f"{small['atoms_active']} active")


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

    # Splitting one implemented clause into three leaves the partition intact and
    # raises the clause ratio. The word ratio does not move, which is why the
    # report carries both.
    whole = library.Script("/tmp/w.json", _good_many(), [])
    split = library.Script("/tmp/s.json", _good_many(), [])
    split.doc["clauses"] = [
        {"text": "[Hidden]", "status": "implemented", "node": "keywords[0]"},
        {"text": "[Action]", "status": "implemented", "node": "keywords[1]"},
        {"text": "[Stun] a", "status": "implemented", "node": "abilities[0]"},
        {"text": "unit.", "status": "implemented", "node": "abilities[0]"},
        {"text": "If you played this from your hand, draw 1.",
         "status": "unsupported", "reason": "r"}]
    whole.doc["clauses"][3]["status"] = "unsupported"
    whole.doc["clauses"][3]["reason"] = "r"
    whole.doc["clauses"][3].pop("node", None)
    a, b = library.coverage([whole]), library.coverage([split])
    check("splitting an implemented clause raises the CLAUSE ratio",
          b["clause_coverage"] > a["clause_coverage"],
          f"{a['clause_coverage']:.2f} -> {b['clause_coverage']:.2f}")
    # Asserted against the arithmetic, not merely against each other: two ratios
    # that are both wrong in the same way are also equal.
    want = a["words_implemented"] / a["words"]
    check("and leaves the WORD ratio where it was",
          abs(a["word_coverage"] - b["word_coverage"]) < 1e-9
          and abs(a["word_coverage"] - want) < 1e-9
          and 0.0 < want < 1.0,
          f"{a['word_coverage']:.4f} vs {b['word_coverage']:.4f}, "
          f"arithmetic says {want:.4f}")
    check("the word ratio is reported, so the pair can be read together",
          0.0 < library.coverage()["word_coverage"] <= 1.0,
          f"{library.coverage()['word_coverage']:.3f}")

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
    # Stability alone is satisfied by a constant, which would make every game log
    # name the same script. Two different bodies have to differ.
    check("two different scripts do not share a version",
          schema.body_hash(_good()) != schema.body_hash(_good_many()),
          "a constant hash is perfectly stable and perfectly useless")
    committed = set(schema.body_hash(s.doc) for s in library.load_all() if s.doc)
    check("every committed script has a version of its own",
          len(committed) == len(library.load_all()), f"{len(committed)} distinct")

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
    """`check <deck>` reports what can be PLAYED, not what is legal.

    Counted INDEPENDENTLY here. The first version of this section asked
    `library.readiness` for the deck's distinct cards and compared the answer to
    `deckfile.distinct_cards` — the function `readiness` calls. Breaking the
    latter kept both sides equal and the checks green, which is a check
    confirming that a function agrees with itself. So the count below is rebuilt
    from the deck file's own entries, and a card known to be scripted is named.
    """
    import deckfile
    deck = deckfile.resolve("irelia-core-meta")
    ready = library.readiness(deck)

    # Rebuilt from the deck's entries, not from the helper under test.
    mine = set()
    for name, _qty in list(deck.main) + list(deck.runes) + list(deck.battlefields):
        card = cards.find(name)
        mine.add(card["name"] if card else name)
    for name in (deck.legend, deck.chosen_champion):
        card = cards.find(name) if name else None
        if card:
            mine.add(card["name"])

    check("readiness counts the deck's distinct cards, independently counted",
          ready["distinct"] == len(mine),
          f"readiness says {ready['distinct']}, counting the file says {len(mine)}")
    check("the legend and the Chosen Champion are inside that count",
          cards.find(deck.legend)["name"] in mine
          and cards.find(deck.chosen_champion)["name"] in mine,
          "neither is shuffled and both are executed every game")
    check("scripted and unscripted partition the deck exactly",
          sorted(ready["scripted"] + ready["unscripted"]) == sorted(mine)
          and not (set(ready["scripted"]) & set(ready["unscripted"])),
          f"{len(ready['scripted'])} + {len(ready['unscripted'])} vs {len(mine)}")
    check("a deck's scripted cards are the ones with a script on disk",
          set(ready["scripted"]) == mine & set(library.by_card()),
          f"{len(ready['scripted'])} scripted")
    check("Irelia, Fervent is in this deck and is scripted",
          "Irelia, Fervent" in ready["scripted"],
          "a named card, so the count cannot be right by construction")
    check("a deck with no scripted card reports zero rather than crashing",
          library.readiness(deck, [])["share"] == 0.0)

    # The name the deck file writes and the name the corpus prints are not always
    # the same string, and 16 corpus cards have both forms. Slugging the raw
    # string made a deck naming one form report the card unscripted with its
    # script sitting right there.
    # The spelling that actually differs is the bare champion name a decklist
    # writes: 46 lookup keys in the corpus slug differently from the card they
    # name, and two of them are scripted. `Irelia - Fervent` and `Irelia,
    # Fervent` are NOT such a pair — a comma and a dash both fold to the same
    # separator — so a check written on that pair passes either way and proves
    # nothing.
    check("a bare champion name reaches the same script as its full name",
          library.slug("Dr. Mundo") == library.slug("Dr. Mundo - Expert")
          == "dr-mundo-expert",
          f'{library.slug("Dr. Mundo")} vs {library.slug("Dr. Mundo - Expert")}')
    check("and so does the other spelling of the subtitle",
          library.slug("Irelia - Fervent") == library.slug("Irelia, Fervent")
          == "irelia-fervent",
          f'{library.slug("Irelia - Fervent")} / {library.slug("Irelia, Fervent")}')
    unreachable = []
    scripted = library.by_card()          # once: the corpus has 1,037 lookup keys
    for key, entry in cards.pool().items():
        if entry.get("ambiguous"):
            continue
        name = entry.get("name")
        if name in scripted and library.slug(key) != library.slug(name):
            unreachable.append("%s -> %s" % (key, name))
    check("every name the corpus knows a scripted card by reaches its script",
          not unreachable, "; ".join(unreachable[:4]))


def every_clause(check):
    """Every clause is validated, not just the first — and they must partition.

    Both halves are load-bearing and neither is obvious. A loop truncated to
    `clauses[:1]` is invisible to a one-clause fixture, and every shipped script
    being valid means truncation changes no committed number: only a defect
    planted in a LATER clause can tell the two apart. And a coverage ratio whose
    denominator the script chooses is not a ratio: delete an `unsupported`
    clause and it rises; invent an implemented one and it rises again.
    """
    for i in range(4):
        errs = _broken_many(
            lambda d, i=i: d["clauses"][i].__setitem__("text", "Draw seventeen cards."))
        err = _find(errs, "clause_not_in_text")
        check(f"a clause the card does not print is caught at index {i}",
              err is not None and err["path"] == f"clauses[{i}].text",
              json.dumps(err))

    err = _find(_broken_many(lambda d: d["clauses"][3].__setitem__("node", "abilities[9]")),
                "bad_clause_ref")
    check("a dangling node reference is caught in the LAST clause too",
          err is not None and err["path"] == "clauses[3].node", json.dumps(err))

    check("the fixture really does have several clauses",
          len(_good_many()["clauses"]) == 4,
          "a one-clause fixture cannot tell a truncated loop from a whole one")

    # -- the partition rule ------------------------------------------------
    err = _find(_broken_many(lambda d: d["clauses"].pop()), "clauses_not_a_partition")
    check("deleting a clause breaks the partition rather than raising coverage",
          err is not None and "left out" in err["message"], json.dumps(err))

    err = _find(_broken_many(lambda d: d["clauses"].append(
        {"text": "[Stun] a unit.", "status": "implemented",
         "node": "abilities[0].effect[0]"})), "clauses_not_a_partition")
    check("repeating a clause breaks the partition rather than raising coverage",
          err is not None and "does not print" in err["message"], json.dumps(err))

    check("a script whose clauses do partition the text is accepted",
          not _find(schema.validate(_good_many()), "clauses_not_a_partition"))

    # Splitting is the inflation the partition rule does NOT catch — the words
    # are the same either way. Two things bound it: the word ratio, which does
    # not move when a clause is cut in half, and the census splitter's own count,
    # vendored beside the scripts.
    counts = library.splitter_counts()
    check("the census splitter's clause counts are vendored beside the scripts",
          len(counts) >= 40, f"{len(counts)} cards")
    over = [(s.card, len(s.clauses), counts.get(s.card))
            for s in library.load_all()
            if s.card in counts and len(s.clauses) > counts[s.card]]
    check("no script claims more clauses than the splitter found in that card",
          not over, "; ".join(f"{c}: {n} > {m}" for c, n, m in over[:4])
          or f"{len(counts)} cards bounded")


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


SECTIONS = (vocabulary, vocabulary_closure, validator_errors, hostile_input,
            script_library, atom_coverage, clause_coverage, version_hashing,
            readiness, every_clause, clause_text)
