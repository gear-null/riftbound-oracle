"""Regression harness — run this after every rules update.

A rules update is the moment this system is most likely to break silently: ids
renumber, examples move, a parser edge case appears. Each check below exists
because something actually went wrong during development, so a regression here
is a real regression, not a hypothetical.

    python3 rules_cli.py selftest

Exit 0 = safe to answer questions against this corpus.
"""
import json, os, re, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

FAILS = []
NOTES = []


def check(name, ok, detail=""):
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}{'  — ' + detail if detail else ''}")
    if not ok:
        FAILS.append(name)
    return ok


def note(msg):
    NOTES.append(msg)
    print(f"  [note] {msg}")


def parser_fidelity():
    """Test parse_doc itself on fixtures.

    The harness previously loaded the committed rules.json and never imported
    parse_rules — so the file with the worst track record had zero coverage,
    and editing the parser without rebuilding still passed green.
    """
    print("\n=== parser fidelity (fixtures) ===")
    import tempfile
    try:
        from parse_rules import parse_doc
    except SystemExit:
        # A skill copied out of the source repo has no markdown to parse. The
        # parser is only exercised when rebuilding, so this is a skip, not a
        # failure — every other check still runs against the vendored corpus.
        note("source corpus absent; parser checks skipped (rebuild-only path)")
        return

    def run(body):
        with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False, encoding="utf-8") as fh:
            fh.write(body)
            path = fh.name
        try:
            return parse_doc("XX", path, "test")
        finally:
            os.unlink(path)

    # Wrapped cross-reference must NOT become a rule (the TR:128 fabrication).
    rules, _, _, vetoed = run("100. Root\n101. Something about gameplay. See CR\n128. Privacy for information types.\n")
    check("wrapped cross-ref is not fabricated as a rule", "128" not in rules, f"vetoed={len(vetoed)}")

    # A repeated id is a continuation and must not corrupt the earlier rule.
    rules, _, _, _ = run("704. Unsporting Conduct\n705. Players may not engage in conduct listed in\n704. Engaging in it is sanctionable.\n")
    check("repeated id does not corrupt the original rule",
          rules["704"]["text"] == "Unsporting Conduct", repr(rules["704"]["text"]))
    check("repeated-id text stays with the rule being read",
          "sanctionable" in rules["705"]["text"], repr(rules["705"]["text"])[:70])

    # The veto must NOT swallow a genuine rule after prose wrapping on in/to.
    rules, _, _, _ = run("416. Recycle\n416.1. Costs are paid in\n417. Deal\n")
    check("prose wrap on 'in' does not swallow the next rule", "417" in rules)
    rules, _, _, _ = run("420. Move\n420.1. A Unit may be assigned to\n421. Hide\n")
    check("prose wrap on 'to' does not swallow the next rule", "421" in rules)

    # Example bleed: a blank line inside an Example must not end it.
    rules, _, _, _ = run("431. Burn Out\n431.2. Completes the remainder of the action.\nExample: A player draws while empty,\n\nrandomizing it as normal.\n")
    check("blank line inside an Example does not bleed into rule text",
          rules["431.2"]["text"] == "Completes the remainder of the action.",
          repr(rules["431.2"]["text"]))
    check("the example tail is captured as an example",
          any("randomizing" in e for e in rules["431.2"]["examples"]))


def corpus_integrity():
    """The parser has fabricated rules and corrupted others before now."""
    print("\n=== corpus integrity ===")
    from verify_citations import RuleIndex
    idx = RuleIndex()
    rules = list(idx.rules.values())
    # `> 3000` against an actual 3316 meant 300 rules could vanish silently.
    EXPECTED = 3316
    drift = abs(len(rules) - EXPECTED) / EXPECTED
    check("rule count within 1% of the recorded corpus", drift <= 0.01,
          f"{len(rules)} rules (expected ~{EXPECTED})")

    orphans = [r for r in rules if r["parent"] and f'{r["doc"]}:{r["parent"]}' not in idx.rules]
    check("no orphaned parents", not orphans, f"{len(orphans)} orphans")

    empty = [r for r in rules if not r["text"].strip()]
    check("no empty rules", not empty, f"{len(empty)} empty")

    broken = [(r["id"], x) for r in rules for x in r["see_also"]
              if f'{r["doc"]}:{x}' not in idx.rules]
    check("no broken cross-refs", not broken, f"{len(broken)} broken")

    # Fabrication signal: a wrapped cross-reference read as a rule definition
    # lands wildly out of document order. This is how TR:128 was caught.
    def key(rid):
        return [(0, int(s), "") if s.isdigit() else (1, 0, s) for s in rid.split(".")]
    disorder = []
    for doc in ("CR", "TR"):
        ids = [r["id"] for r in rules if r["doc"] == doc]
        ids_sorted = sorted(ids, key=key)
        if ids != ids_sorted:
            # Only report genuine inversions, not sort-stability noise.
            for a, b in zip(ids, ids[1:]):
                if key(b) < key(a):
                    disorder.append(f"{doc}:{a}->{b}")
    # One known-real defect in Riot's own PDF: TR 601.3.c.5.a precedes 601.3.c.4.b.
    unexpected = [d for d in disorder if "601.3.c" not in d]
    check("no out-of-order ids beyond the known Riot defect", not unexpected,
          f"{len(disorder)} total, {len(unexpected)} unexpected")

    # Example bleed: example text appended to a rule's own text.
    bleed = [r for r in rules if r["text"].rstrip().endswith(",")]
    check("no rule text ends mid-clause (example-bleed signal)", not bleed,
          ", ".join(f'{r["doc"]}:{r["id"]}' for r in bleed[:3]))
    return idx


def verifier_regression(idx):
    """Every case here is a real citation error caught during development."""
    print("\n=== citation verifier ===")
    from verify_citations import verify_citation
    bad = [
        ("194.2.b", "The Victory Score is 8 points by default."),          # wrong sub-clause
        ("471.1.b.1", "points Gained from sources that are not Conquer are not beholden to these restrictions"),
        ("999.9.z", None),                                                  # fabricated id
        ("343.1", "Focus passes to the next Player in Turn Order"),         # stale after renumber
    ]
    caught = sum(1 for rid, q in bad if not verify_citation(idx, rid, q).ok)
    check("rejects known-bad citations", caught == len(bad), f"{caught}/{len(bad)}")

    good = [
        ("194.3", "The Victory Score is 8 points by default."),
        ("471.1.a.1", "points Gained from sources that are not Conquer are not beholden to these restrictions"),
        ("829.1.b.1", "Banishing the spell in this way is a delayed replacement effect"),
    ]
    passed = sum(1 for rid, q in good if verify_citation(idx, rid, q).ok)
    check("accepts known-good citations", passed == len(good), f"{passed}/{len(good)}")

    narrowed = verify_citation(idx, "829", "Banishing the spell in this way is a delayed replacement effect")
    check("narrows a vague cite to the tightest rule", narrowed.cite_as == "829.1.b.1",
          f"829 -> {narrowed.cite_as}")

    # Cross-document mis-attribution: a CR-only id cited as TR must NOT resolve.
    cross = verify_citation(idx, "194.3", "The Victory Score is 8 points by default.", doc="TR")
    check("rejects a CR rule cited as TR", not cross.ok, "; ".join(cross.problems)[:60])

    # A doc-prefixed id must verify identically to the split form.
    pref = verify_citation(idx, "CR:194.3", "The Victory Score is 8 points by default.")
    check("accepts the doc-prefixed cite form", pref.ok, "; ".join(pref.problems)[:60])

    # A cite with no quote ran no quote check and must not read as verified.
    noq = verify_citation(idx, "194.3")
    check("a cite with no quote is not 'checked'", noq.ok and not noq.checked)


def holding_invariants(idx):
    """Error concentrated in the one-line summary, so it is checked hardest."""
    print("\n=== holding-line invariants ===")
    from render_report import verify_answer
    import copy
    src = os.path.join(HERE, "demo-answer.json")
    if not os.path.exists(src):
        note("demo-answer.json missing; skipping")
        return
    base = json.load(open(src, encoding="utf-8"))

    ok = verify_answer(copy.deepcopy(base), idx)
    check("known-good answer passes", not ok["_problems"], "; ".join(ok["_problems"][:2]))

    loose = copy.deepcopy(base)
    loose["holding"]["spans"] = [{"text": "Not while", "basis": "grounded", "note": "n5"}]
    r = verify_answer(loose, idx)
    check("rejects a span claiming more support than its note",
          any("claims grounded" in p for p in r["_problems"]))
    check("rejects an under-decomposed holding line",
          any("covered by typed spans" in p for p in r["_problems"]))

    nocrux = copy.deepcopy(base)
    for n in nocrux["notes"]:
        n.pop("crux", None)
    r = verify_answer(nocrux, idx)
    check("requires exactly one crux", any("must be crux" in p for p in r["_problems"]))

    ca = copy.deepcopy(base)
    ca["counterargument"] = [{"reading": "x", "why_it_loses": "y",
                              "cites": [{"rule": "CR:999.9.z", "quote": "invented"}]}]
    r = verify_answer(ca, idx)
    check("a failed COUNTERARGUMENT cite forces UNSETTLED",
          r["holding"]["disposition"] == "UNSETTLED", f'-> {r["holding"]["disposition"]}')

    weird = copy.deepcopy(base)
    weird["notes"][0]["basis"] = "definitional"
    try:
        r = verify_answer(weird, idx)
        ok = any("unknown basis" in p for p in r["_problems"])
    except Exception as exc:
        ok = False
        r = {"_problems": [f"crashed: {exc}"]}
    check("an unknown note basis is reported, not crashed", ok)

    ghost = copy.deepcopy(base)
    ghost["notes"][0]["cites"] = [{"rule": "CR:999.9.z", "quote": "invented"}]
    r = verify_answer(ghost, idx)
    check("forces UNSETTLED when a citation fails",
          r["holding"]["disposition"] == "UNSETTLED", f'-> {r["holding"]["disposition"]}')


def rulebook_and_links():
    """The report's citation links must land on real anchors.

    A citation that expands but cannot be followed was the gap this closes, so
    the failure mode to guard is a link pointing at an anchor the rulebook does
    not define — invisible until a reader clicks it.
    """
    print("\n=== rulebook anchors + report links ===")
    import json as _json
    from corpus import rules_json, rulebook_html_path
    from render_rulebook import render_rulebook, anchor

    rules = _json.load(open(rules_json(), encoding="utf-8"))
    book = render_rulebook(rules, "test")
    ids = set(re.findall(r'<section class="r[^"]*" id="([^"]+)"', book))
    want = {anchor(r["doc"], r["id"]) for r in rules}
    check("every rule gets an anchor", ids == want,
          f"{len(ids)} anchors for {len(want)} rules")

    internal = set(re.findall(r'href="#([^"]+)"', book))
    check("no rulebook link points at a missing anchor", internal <= ids,
          ", ".join(sorted(internal - ids)[:3]))

    # A citation rendered by the report must resolve against that same scheme.
    from render_report import verify_answer, render
    from verify_citations import RuleIndex
    idx = RuleIndex()
    src = os.path.join(HERE, "demo-answer.json")
    if os.path.exists(src):
        ans = verify_answer(json.load(open(src, encoding="utf-8")), idx)
        html = render(ans, idx)
        targets = set(re.findall(r'href="\.\./data/rules\.html#([^"]+)"', html))
        check("report emits rulebook links", bool(targets), f"{len(targets)} distinct")
        check("every report link resolves in the rulebook", targets <= ids,
              ", ".join(sorted(targets - ids)[:3]))

    if not os.path.exists(rulebook_html_path()):
        note("data/rules.html not built yet; run `rules_cli.py rulebook`")


def card_rendering():
    """Cards silently never rendered: the schema had no `cards` field at all."""
    print("\n=== card resolution ===")
    from render_report import resolve_cards
    from corpus import load_cards

    cards = load_cards()
    if not cards:
        note("data/cards.json missing; run `npm run oracle skill-data`")
        return
    check("card data is present", len(cards) > 100, f"{len(cards)} lookup names")

    withart = sum(1 for c in cards.values() if c.get("image"))
    check("cards carry artwork URLs", withart > 0, f"{withart}/{len(cards)}")

    sample = next(iter(cards.values()))["name"]
    got = resolve_cards({"cards": [sample]})
    check("a named card resolves to text + artwork",
          len(got) == 1 and got[0]["name"] == sample and not got[0].get("unresolved"))

    missing = resolve_cards({"cards": ["Definitely Not A Real Card"]})
    check("an unresolvable name is marked, not dropped",
          len(missing) == 1 and missing[0].get("unresolved"))

    check("no cards field renders nothing", resolve_cards({}) == [])


def main():
    print("rules-report selftest")
    parser_fidelity()
    idx = corpus_integrity()
    verifier_regression(idx)
    holding_invariants(idx)
    rulebook_and_links()
    card_rendering()

    print()
    if FAILS:
        print(f"FAILED {len(FAILS)}: {', '.join(FAILS)}")
        sys.exit(1)
    print("all checks passed — safe to answer against this corpus")
    sys.exit(0)


if __name__ == "__main__":
    main()
