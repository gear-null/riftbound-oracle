"""Regression harness — run this after every rules update.

A rules update is the moment this system is most likely to break silently: ids
renumber, examples move, a parser edge case appears. Each check below exists
because something actually went wrong during development, so a regression here
is a real regression, not a hypothetical.

    python3 rules_cli.py selftest

Exit 0 = safe to answer questions against this corpus.
"""
import glob, json, os, re, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

FAILS = []
NOTES = []
RAN = [0]


def check(name, ok, detail=""):
    RAN[0] += 1
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}{'  — ' + detail if detail else ''}")
    if not ok:
        FAILS.append(name)
    return ok


def note(msg):
    NOTES.append(msg)
    print(f"  [note] {msg}")


def safely(fn, fallback, label):
    """Run something that may be broken, turning a crash into a failed check.

    MODULE LEVEL, and that is the point. This started nested inside one check
    group, so every group written afterwards called into flowgraph bare — and a
    mutant that breaks the layout took the whole suite down three separate
    times, reported as "<suite crashed>": detection by traceback rather than by
    the check whose job it is. A check that only holds while the code is healthy
    is not a check, and a guard that only exists in one function is a guard the
    next function will not use.

    Reaches `note` so the exception is visible, and returns a fallback the
    caller can assert against. Callers must still guard a NEGATIVE assertion
    with `bool(result)` — an empty fallback satisfies "does not contain X".
    """
    try:
        return fn()
    except Exception as exc:
        note(f"{label} raised {type(exc).__name__}: {exc}")
        return fallback


def diagram_complaint(body, labels):
    """What is wrong with a committed SVG, or None if nothing is.

    A FUNCTION, not three inline branches, because the battery mutates Python
    and not data files: inline, these could only be exercised by corrupting a
    committed diagram on disk, so no mutant could reach them and they were
    pinned by nothing. Pulled out, they are checked directly against synthetic
    input below and a mutant can break them.

    Deliberately shallow. It answers the two questions a committed picture must
    answer for itself — did the renderer finish, and does it draw the arrows its
    own IR declares — and not "is this the same bytes Fireworks produces today",
    which would go red on any version bump of theirs and teach everyone to
    ignore it.
    """
    if not body.rstrip().endswith("</svg>"):
        return "the committed SVG is truncated"
    drawn = sorted(int(n) for n in
                   re.findall(r'class="fg-num"[^>]*>(\d+)</text>', body))
    if drawn and sorted(labels) and drawn != sorted(labels):
        return f"the SVG draws {drawn} but the IR declares {sorted(labels)}"
    return None


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
    # EXACT, not within 1%. The tolerance was 33 rules — enough for a parser
    # change to drop or fabricate a dozen and still report healthy. The corpus
    # is a fixed document; its rule count is known, and a real rules update is
    # supposed to change this number deliberately.
    check("rule count matches the recorded corpus exactly", len(rules) == EXPECTED,
          f"{len(rules)} rules, expected {EXPECTED} — if a rules update landed, "
          "bump EXPECTED in the same commit")

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

    # The overlay is delegated off one literal selector list, and titles itself
    # by regex-matching the href against render_rulebook.anchor()'s format. Both
    # are undeclared contracts with the renderer: rename a link class while
    # restyling and the overlay silently stops intercepting, so the reader gets
    # navigated out of the report instead of the panel.
    if os.path.exists(src):
        # Union across every fixture: demo emits only anc-link and
        # rulebook-link, so dropping `a.card-rule, a.sym-rule` from the
        # interception selector left this check green while those links
        # navigated the reader out of the report.
        emitted = set()
        for _f in ("demo", "viktor", "heron", "flow-counter", "vi-cost"):
            _p = os.path.join(HERE, f"{_f}-answer.json")
            if not os.path.exists(_p):
                continue
            _h = render(verify_answer(json.load(open(_p, encoding="utf-8")), idx), idx)
            emitted |= set(re.findall(
                r'<a class="([^"]+)"[^>]*href="\.\./data/rules\.html', _h))
        # rb-pop is the panel's own "open full page" link; it is meant to escape
        # the overlay, so it is deliberately not intercepted.
        emitted.discard("rb-pop")
        sel = re.search(r"closest\('((?:[^']*rulebook-link[^']*))'\)", html)
        listed = {re.sub(r"^a\.", "", s.strip()) for s in sel.group(1).split(",")} if sel else set()
        check("the overlay intercepts every class the renderer links with",
              bool(listed) and emitted <= listed,
              f"emitted {sorted(emitted)} vs handled {sorted(listed)}")

        # The panel title parses the anchor; a format change silently degrades
        # every panel to the generic "Rulebook".
        from render_rulebook import anchor
        pat = re.search(r"/#\(\[A-Z\]\{2\}\)-\(\.\+\)\$/", html)
        check("the overlay title regex still matches the anchor format",
              bool(pat) and bool(re.match(r"^[A-Z]{2}-.+$", anchor("CR", "471.1.b.1"))),
              anchor("CR", "471.1.b.1"))

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

    # Stats travelled as markdown once and printed with the asterisks showing.
    from render_report import stats_html, esc
    # `cardStats` always returns a fully-shaped dict, so truthiness proves
    # nothing: an upstream field rename yields all-null stats for every card and
    # a green suite. Assert VALUES against measured floors instead.
    def n_with(key):
        return sum(1 for c in cards.values() if (c.get("stats") or {}).get(key) is not None)
    check("most cards carry an energy value", n_with("energy") > 700, f'{n_with("energy")}/{len(cards)}')
    check("every card carries a type", n_with("type") == len(cards), f'{n_with("type")}/{len(cards)}')
    check("every card carries a domain",
          sum(1 for c in cards.values() if (c.get("stats") or {}).get("domain")) > 900)
    check("might and power are populated where they apply",
          n_with("might") > 400 and n_with("power") > 300,
          f'might={n_with("might")} power={n_with("power")}')
    check("no card text contains markdown bold",
          not any("**" in c.get("text", "") for c in cards.values()))

    vi = cards.get("vi - hotheaded")
    if vi:
        chips = stats_html(vi["stats"])
        check("stats render as chips, not prose", 'class="chip"' in chips and "**" not in chips)

    # Answer JSON may supply a card object, so stats are untrusted input.
    for shape in ("4 Energy", ["a"], 7, None, {"domain": "Fury"}, {"energy": True}):
        try:
            html = stats_html(shape)
        except Exception as exc:
            check(f"stats_html survives {shape!r}", False, repr(exc)); break
    else:
        check("stats_html survives hostile shapes", True)
    check("a string domain is one chip, not one per letter",
          stats_html({"domain": "Fury"}).count("chip-d") == 1)
    check("a boolean is not rendered as a stat value",
          "Energy" not in stats_html({"energy": True}))

    # Data invariants that a regeneration must not quietly break. Regenerating
    # used to churn 27 entries and rebind 5 base names to different cards,
    # because the fold depended on API page order.
    treatments = [v["name"] for v in cards.values()
                  if str((v.get("stats") or {}).get("rarity", "")).lower()
                  in ("promo", "showcase")]
    check("no card reports a print treatment as its rarity", not treatments,
          f"{len(treatments)}: {treatments[:2]}")

    ambiguous = {k: v for k, v in cards.items() if v.get("ambiguous")}
    check("base names shared by different cards are flagged", len(ambiguous) > 0,
          f"{len(ambiguous)} flagged (e.g. {sorted(ambiguous)[:3]})")
    check("every flagged alias lists at least two full names",
          all(len(v["ambiguous"]) > 1 for v in ambiguous.values()))

    # Equipment gear prints its granted effect only on the artwork, so the
    # API's text is short. The gap must stay VISIBLE: a flagged card is honest,
    # a silently short one invites "the card has no such ability".
    incomplete = sorted({v["name"] for v in cards.values() if v.get("incomplete")})
    # Every equipment card the API truncates must be covered by a transcription.
    # A gap here is not a crash, it is a card whose granted effect a reader
    # cannot see — so it fails rather than merely noting.
    check("no card is missing text the API does not carry", not incomplete,
          f"{len(incomplete)} await transcription: {', '.join(incomplete[:4])}")

    equipped = [v for v in cards.values() if "Grants +" in v.get("text", "")]
    check("equipment carries its granted Might", len(equipped) > 20,
          f"{len({v['name'] for v in equipped})} cards")
    check("every flagged card explains what is missing",
          all(isinstance(v.get("incomplete"), str) and v["incomplete"]
              for v in cards.values() if v.get("incomplete")))

    # A transcribed card must actually carry its granted effect and lose the flag.
    axe = cards.get("blighted battleaxe")
    if axe:
        check("a transcribed card carries its granted effect",
              "Might" in axe["text"] and not axe.get("incomplete"),
              axe["text"][-46:])

    # Preview surfaces (Claude Desktop, artifact panes) block remote images, so
    # a linked card shows the offline placeholder even with a working network.
    # Embedding must therefore produce a report with NO remote image refs.
    import render_report as _rr
    _envval = os.environ.get("RIFTBOUND_EMBED_ART", "")
    check("artwork embedding is off unless the env var asks for it",
          _rr.EMBED_ART == (_envval.lower() in ("1", "true", "yes")),
          f"EMBED_ART={_rr.EMBED_ART} for {_envval!r}")
    check("a failed fetch degrades to None rather than raising",
          _rr.embed_image("https://invalid.invalid/x.png", timeout=3) is None)
    _t0 = __import__("time").monotonic()
    check("an empty url is refused without a fetch",
          _rr.embed_image("") is None and (__import__("time").monotonic() - _t0) < 0.05,
          "returned None, but only after attempting a request")

    # Card text comes from a third-party database that lags Riot by months. We
    # crawl Riot's errata ourselves, so holding both and showing the stale one
    # is a contradiction inside our own corpus.
    errata_cards = {v["name"] for v in cards.values() if v.get("errata")}
    check("Riot errata has been applied to the card pool", len(errata_cards) > 10,
          f"{len(errata_cards)} corrected")
    wolf = cards.get("stalking wolf")
    if wolf:
        check("a known errata'd card carries the corrected wording",
              "ambush" in wolf["text"].lower().split("as an additional cost")[-1],
              wolf["text"][-52:])

    # A cost printed on a card must survive into the rendered panel. Unmapped
    # shortcodes were once replaced with a space, deleting the price outright.
    from card_bridge import CardBridge
    bridge = CardBridge()
    costed = [c for c in bridge.cards.values() if re.search(r":rb_(energy|rune)", c.get("text", ""))]
    lost = [c["name"] for c in costed
            if not re.search(r"\[[0-9A-Z]\]", bridge.card_terms(c)["text"])]
    check("no card loses its printed cost in rendering", not lost,
          f"{len(costed)} costed cards, {len(lost)} lost: {lost[:2]}")

    # Every card must render without crashing, whatever its shape.
    crashed = []
    for c in bridge.cards.values():
        try:
            stats_html(bridge.card_terms(c).get("stats"))
        except Exception as exc:
            crashed.append(f'{c["name"]}: {exc}')
    check("every card in the pool renders", not crashed, "; ".join(crashed[:2]))

    # Long card text must ANNOUNCE that it was cut. A hard slice ended one card
    # mid-sentence with no marker, reading as the card's complete text.
    from card_bridge import _clip
    check("short card text is left alone", _clip("abc", 300) == "abc")
    clipped = _clip("word " * 100, 60)
    check("long card text is marked as truncated", clipped.endswith(" …"), repr(clipped[-14:]))
    check("truncation cuts at a word boundary", "  " not in clipped and len(clipped) <= 62)

    # `s or ""` blanked a legitimate zero; 7 cards cost 0 Energy.
    check("a zero stat is not blanked", esc(0) == "0")
    zero = [c for c in cards.values() if (c.get("stats") or {}).get("energy") == 0]
    if zero:
        check("a 0-Energy card still shows its cost",
              "0</b>" in stats_html(zero[0]["stats"]), zero[0]["name"])

    # ---- extraction artifacts in card text (invariant 5) --------------------
    # `Gemhand Hunter` shipped with `ambush` welded onto the `.)` that ended its
    # text. It is not a keyword and never was — every genuine Ambush card
    # brackets it at the START with reminder text — but it read as one, and two
    # agents built decks around an ability the card does not have. The pipeline
    # now strips that shape on the way in; this is the second opinion, and it is
    # deliberately the wider of the two.
    from corpus import artifact_complaints

    # The corpus assertion. Green today, and it is a REGRESSION check: it earns
    # its place on the pull that reintroduces the class, not on this one.
    live = artifact_complaints(cards)
    check("no card in the corpus carries a fused extraction artifact",
          not live, f"{len(live)} found: {live[:3]}")

    # ...which on its own would pass just as well if this function returned []
    # unconditionally. These are the checks that make the one above mean
    # something, and they are why the detector is testable at all rather than
    # only observable on a bad pull.
    check("a fused artifact at the end of card text is detected",
          artifact_complaints({"k": {"name": "Fake", "text": "where you have units.)ambush"}}))

    # The axis that matters. `stripTrailingArtifact` is anchored to end-of-
    # string because it DELETES; this only reports, so it must see the same
    # damage mid-sentence, where the stripper structurally cannot. Narrow this
    # to match the stripper and the pair collapses into one opinion asked twice.
    check("a fused artifact mid-sentence is detected, which the stripper cannot see",
          artifact_complaints({"k": {"name": "Fake", "text": "Deal 2.)ambush then draw."}}))

    # Riftbound symbol markup is `:rb_might:`. Admitting `:` to the punctuation
    # class takes the corpus check from 0 complaints to 1,183 — every symbol on
    # every card — which would then be silenced with an allowlist that hides the
    # real thing.
    #
    # This check has NO mutant of its own, and cannot: the corpus carries 1,183
    # symbol tokens, so every mutation that breaks this one floods the corpus
    # check in the same run. They are two observations of one decision, not two
    # defences. The corpus check is the one filed as invariant 5's pin, because
    # it is the one that fails against real data; this states the reason in a
    # form a reader can see without running anything.
    # THE CAPITALISED KEYWORD. Every one of the 35 bracketed keywords in this
    # corpus is capitalised, so a fused keyword arrives as `.)Ambush` — and both
    # halves of the pair required lowercase. `Gemhand Hunter` was lowercase by
    # luck, and the reasoning in `corpus.py` had it backwards.
    check("a capitalised keyword fused at the end of the text is detected",
          artifact_complaints({"k": {"name": "Fake",
                                     "text": "play me as a Reaction.)Ambush"}}))
    # ...while the benign mid-text seam it would otherwise flag stays silent.
    # 357 cards carry that shape; anchoring is what makes the capital rule free.
    check("a mid-text capital seam is still not an artifact",
          not artifact_complaints({"k": {"name": "Fake",
                                         "text": "Deal 2.)Each player draws."}}))

    # THE OTHER TWO WIDENING AXES. The docstring claims three — unanchored, a
    # larger punctuation class, a two-letter floor — and only the anchor was
    # pinned. Every fixture used `ambush` (six letters) after `.)`, so
    # collapsing the class and the floor back to the stripper's own
    # (`[).!][a-z]{3,}`) left the suite green and the pair became one opinion
    # asked twice.
    check("a fusion after a comma or semicolon is detected",
          artifact_complaints({"k": {"name": "Fake", "text": "a unit,gains two"}})
          and artifact_complaints({"k": {"name": "Fake", "text": "a unit;gains two"}}))
    # MID-TEXT, or the tail rule answers instead of the floor. The first version
    # used `units.)ab` — which ends in the fusion, so `FUSED_ARTIFACT_TAIL`
    # matched it and raising the floor to three left the check green. A fixture
    # reachable by two rules tests whichever one you were not thinking about.
    check("a two-letter fusion is detected, not just a long one",
          artifact_complaints({"k": {"name": "Fake",
                                     "text": "you have units.)ab then draw."}}))

    check("symbol markup is not mistaken for an artifact",
          not artifact_complaints({"k": {"name": "Fake",
                                         "text": "give a unit +1 :rb_might: this turn."}}))

    # A corpus this cannot read is a corpus it cannot report on. `safely` is what
    # makes this fail BY NAME rather than take the suite down with it: without
    # the isinstance guard the scan raises AttributeError, `safely` notes it and
    # returns the fallback, and this line goes red instead of the run ending here.
    malformed = safely(lambda: artifact_complaints(
        {"a": "not a dict", "b": None, "c": {"text": 42},
         "d": {"name": "Real", "text": "units.)ambush"}}), None, "artifact scan")
    check("a malformed card entry is skipped, not raised on",
          malformed is not None and len(malformed) == 1, repr(malformed))


def export_and_history(idx):
    """A shared report carries its evidence, or it is not written.

    The failure this group exists for is invisible on the machine that makes
    the export: a report reaches out for `../data/rules.html` and for artwork on
    Riot's CDN, and BOTH resolve here. So the file looks complete locally and
    arrives at the reader with its evidence links dead — which is worse than an
    obviously broken file, because nothing on the page says so.

    That is why the checks below assert what ARRIVED. An earlier version only
    asserted that nothing still pointed outward, and shipped a file whose
    rulebook link read "open full page" and went to `#`.
    """
    print("\n=== export and history ===")
    import export_report as E
    import corpus as _c

    # RENDER THE FIXTURE, do not go looking for one.
    #
    # This group used to read `reports/flow-counter.html` and skip with a note
    # when it was absent. `reports/` is a working directory that git does not
    # track and that `mutants.py` deliberately excludes from the copy it
    # mutates — so the entire group skipped inside the battery, and all ten
    # export mutants survived while every check passed individually here.
    #
    # That is the "check that cannot run when it matters" defect, one level up
    # from the early return fixed two commits ago: not a check that cannot
    # fail, but a whole group that quietly does not execute in the one
    # environment built to prove it can. A `note()` is not a failure, so
    # nothing said so.
    #
    # Rendering from a shipped answer removes the dependency entirely. It runs
    # wherever the skill runs.
    import render_report
    from render_report import verify_answer
    ans = verify_answer(json.load(open(os.path.join(HERE, "flow-counter-answer.json"),
                                      encoding="utf-8")), idx)
    if ans["_problems"]:
        check("the shipped sample answer still verifies, so export can be tested",
              False, f"{len(ans['_problems'])} problem(s): {ans['_problems'][:2]}")
        return
    html = safely(lambda: render_report.render(ans, idx), "", "render the fixture")
    check("a report can be rendered for the export checks to run against",
          bool(html) and "rb-frame" in html,
          f"{len(html)} bytes rendered" if html
          else "no report to export — every export check below would be vacuous")
    if not html:
        return
    rules = open(_c.rulebook_html_path(), encoding="utf-8").read()
    stub = lambda u: "data:image/png;base64,AAAA"

    # The embedded rulebook is inspected DIRECTLY, because everything above
    # asks about the wrapper. The first version of `build_minibook` looked for
    # a sentinel that occurs zero times in the rulebook and fell back to a
    # blind 4000-character slice on every rule — carrying ~100 uncited rules,
    # leaving 17 sections unclosed, and ending mid-attribute. No cited rule was
    # truncated, but only because the longest rule in the corpus is 2,000
    # characters: a margin upstream of us that nobody chose. These check the
    # property rather than that margin.
    cited = E._cited_anchors(html)
    minibook = safely(lambda: E.build_minibook(cited, rules), "", "minibook")
    got = set(re.findall(r'id="((?:CR|TR)-[^"]+)"', minibook))
    check("the embedded rulebook carries every rule the report cites",
          set(cited) <= got, f"missing {sorted(set(cited) - got)[:4]}")
    check("the embedded rulebook carries NOTHING the report does not cite",
          got <= set(cited), f"{len(got - set(cited))} uncited rule(s) rode along")
    check("every rule in the embedded rulebook arrives whole",
          minibook.count("<section") == minibook.count("</section>")
          and minibook.count("<section") == len(cited),
          f"{minibook.count('<section')} open, {minibook.count('</section>')} "
          f"closed, {len(cited)} cited")

    # The whole-block guard, exercised DIRECTLY. It is a backstop behind the
    # end-tag search, so no single-site mutation of correct code reaches it —
    # which by this repo's own rule means it would be defended by nothing and
    # reported as covered. Feeding it a rulebook whose section never closes is
    # what makes it a real guard rather than a comforting one.
    # Tear the closing tag off THE CITED RULE, not off the file's first
    # section — removing an unrelated one leaves this rule's block perfectly
    # well-formed, and the check passed while proving nothing.
    # Every lookup here is guarded. Two mutants — renaming the generated
    # rulebook, and changing the anchor format — leave `cited` empty or the id
    # absent, and the raw `cited[0]` / `.index()` this used took the whole run
    # down with IndexError and ValueError. The battery scores that as
    # "detected, but not by the check it is filed under", which is right and is
    # a real loss: the defect was found and the check meant to name it never
    # got to speak.
    def tear_and_ask():
        one = cited[0]
        at = rules.index(f'id="{one}"')
        shut = rules.index("</section>", at)
        torn = rules[:shut] + rules[shut + len("</section>"):]
        try:
            E.build_minibook([one], torn)
        except E.ExportRefused as err:
            return str(err)
        return ""

    why = safely(tear_and_ask, None, "tear a rule block")
    # The export's spine guarantee is not the exporter's to keep. `build_minibook`
    # carries the anchors it is given; the ancestors are there only because the
    # RENDERER links them. Pin it where it actually lives, or the spine could
    # quietly disappear from every export while the exporter stayed correct and
    # its docstring went on promising a spine.
    # Scoped to CITATION links. `sym-rule` and `card-rule` point at the rule
    # defining a symbol or a keyword, and those legitimately have no spine
    # rendered — the first version of this check flagged two of them and would
    # have failed an honest report, which is the failure mode recorded in
    # known-issues.md arriving one check later.
    cite_ids = {m.group(1) for m in re.finditer(
        r'<a class="(?:anc-link|rulebook-link)"[^>]*href="[^"]*#(?:CR|TR)-([^"]+)"', html)}
    orphans = [r for r in cite_ids
               if "." in r and r.rsplit(".", 1)[0] not in cite_ids]
    check("a report links a citation's ancestor spine, which is what puts it in an export",
          not orphans and bool(cite_ids),
          f"{len(orphans)} cited rule(s) with no linked parent: {sorted(orphans)[:4]}"
          if orphans else f"{len(cite_ids)} citation link(s), spine intact")

    check("a rule block that is not one whole section is refused",
          why is not None and ("whole" in why or "never closed" in why),
          f"got {why[:80]!r}" if why is not None
          else "could not construct the torn case — see the note above")

    doc = safely(lambda: E.export(html, rules, fetch=stub), "", "export")
    check("an export is produced from a rendered report", bool(doc))
    if not doc:
        return

    remote = re.findall(r'(?:src|href)="https?://', doc)
    check("nothing in an export points outside the file",
          not remote, f"{len(remote)} remote reference(s) remain")

    # ...and the other direction, which is the one that was missed. A file with
    # its rulebook deleted passes the check above perfectly.
    check("an export carries the rulebook it cites", 'id="rb-doc"' in doc)


    check("an export carries the loader that shows it", "fr.srcdoc=doc" in doc)
    check("an export inlines every image the report had",
          doc.count("data:image/") >= len(E.REMOTE_IMG.findall(html)),
          f"{len(E.REMOTE_IMG.findall(html))} in, {doc.count('data:image/')} out")
    check("an export stops promising a full rulebook it does not carry",
          "open full page" not in doc.lower(),
          "the overlay still offers a page that is not in the file")

    # Each refusal below is asserted BY ITS REASON, not merely by "something
    # refused". The exporter guards the same property twice on purpose — an
    # internal raise, then a final sweep of the finished document — and a
    # mutation battery changes one site at a time, so a check that accepts any
    # refusal reports both guards as covered while neither is pinned. Naming
    # the reason is what tells them apart. `docs/invariants.md` has the general
    # form of this; the export is where it bit most recently.
    def refusal(fetch=None, doc_html=None, doc_rules=None):
        try:
            E.export(doc_html or html, doc_rules or rules, fetch=fetch or stub)
            return ""
        except E.ExportRefused as err:
            return str(err)

    why = refusal(fetch=lambda u: None)
    check("one image that cannot be inlined refuses the whole export",
          "could not be inlined" in why and "nothing was written" in why,
          f"got {why[:90]!r}")

    why = refusal(doc_html=html.replace(
        '<iframe class="rb-frame" id="rb-frame" title="Rulebook"></iframe>', "", 1))
    check("an export refuses when the overlay markup it rewrites is gone",
          "expected exactly one" in why, f"got {why[:90]!r}")

    why = refusal(doc_rules=rules.replace('id="CR-829.1.c"', 'id="CR-NOPE"', 1))
    check("an export refuses when the rulebook lacks a rule the report cites",
          "no anchor for" in why, f"got {why[:90]!r}")

    why = refusal(doc_html="<html><body>no citations here</body></html>")
    check("an export refuses input that is not a rendered report",
          "links no rules" in why, f"got {why[:90]!r}")

    # The history page is derived from the directory, so it cannot list a
    # report that is not there.
    import rules_cli
    # Same reason the fixture above is rendered rather than found: `reports/`
    # is untracked and the battery excludes it, so reading whatever happens to
    # be in it made these checks pass here and skip there. Write known files,
    # assert against them, remove them.
    # Same reason the fixture above is rendered rather than found: `reports/`
    # is untracked and `mutants.py` excludes it from the copy it mutates, so
    # reading whatever happens to be in it made these checks pass here and skip
    # in the battery. Write known files, assert against them, remove them.
    os.makedirs(rules_cli.REPORTS, exist_ok=True)
    plain = os.path.join(rules_cli.REPORTS, "_selftest_plain.html")
    port = os.path.join(rules_cli.REPORTS, "_selftest_port.html")
    try:
        open(plain, "w", encoding="utf-8").write(html)
        open(port, "w", encoding="utf-8").write(doc)
        records = safely(rules_cli._report_records, [], "report records")
        names = {r["file"] for r in records}
        check("the history lists the reports that exist",
              {"_selftest_plain.html", "_selftest_port.html"} <= names,
              f"{len(records)} record(s), missing "
              f"{sorted({'_selftest_plain.html', '_selftest_port.html'} - names)}")
        check("the history does not list itself as a report",
              not any(r["file"] == rules_cli.INDEX_NAME for r in records))

        # The portable marker is APPENDED after the overlay, ~2.5MB into a
        # 2.6MB file, so a head-only scan never saw it and the column was
        # decorative: every report listed as not-portable, including the
        # portable ones. A flag that cannot be true is the same defect as a
        # check that cannot fail.
        portable = {r["file"] for r in records if r["portable"]}
        check("an exported report is listed as portable",
              "_selftest_port.html" in portable,
              f"{len(portable)} of {len(records)} marked portable")
        check("a plain report is not listed as portable",
              "_selftest_plain.html" not in portable,
              "the un-exported fixture is claimed portable"
              if "_selftest_plain.html" in portable else "correctly unmarked")
    finally:
        for f in (plain, port):
            if os.path.exists(f):
                os.remove(f)

    # The index must be refreshed by `report`, not only by `reports`. An index
    # that updates on a second command nobody is told to run is stale by
    # default, and stale in the worst way: it lists every answer except the one
    # just written, which is the one its reader came for.
    src_lines = open(os.path.join(HERE, "rules_cli.py"), encoding="utf-8").read()
    body = safely(
        lambda: src_lines[src_lines.index("def cmd_report("):
                          src_lines.index("def cmd_render(")],
        "", "locate cmd_report")
    check("writing a report refreshes the history index",
          "write_report_index()" in body,
          "cmd_report calls it" if "write_report_index()" in body
          else "cmd_report never updates the index, so `reports` must be run by hand")

    # Diagrams used to land in `reports/` beside the answers, so the folder a
    # user browses held `combat.svg` and `ok.fireworks.json` as siblings of the
    # documents. Separated rather than filtered: a reader should not have to
    # know which extensions to ignore.
    check("a diagram is written under reports/diagrams, not among the reports",
          os.path.basename(rules_cli.DIAGRAMS) == "diagrams"
          and os.path.dirname(rules_cli.DIAGRAMS) == rules_cli.REPORTS,
          rules_cli.DIAGRAMS)


def primer_invariants(idx):
    """The primer document kind: routing, the transition rule, and the diagram.

    A primer is prose, and prose is where a model's fluency does the most
    damage — so the checks that matter are the ones proving the page cannot
    assert more than the citations carry. Two properties are new here and
    neither exists on the ruling path:

      * a transition is a claim, and an uncited one fails verification
      * the diagram is derived, so it cannot draw an arrow nobody declared

    Both are pinned below, and both are pinned by mutants in mutants.py.
    """
    print("\n=== primer: routing ===")
    import copy
    import tempfile
    from render_primer import all_cites, render, verify_primer

    src = os.path.join(HERE, "hot-fepr-primer.json")
    # FAIL, not skip. A note does not reach the exit code, so removing the
    # fixture took the run from 267 checks to 213 while reporting two unrelated
    # failures and nothing at all about the fifty that never ran.
    if not check("the primer fixture is present", os.path.exists(src),
                 "without it none of the primer checks run"):
        return
    base = json.load(open(src, encoding="utf-8"))


    good = verify_primer(copy.deepcopy(base), idx)
    check("the shipped primer verifies clean", not good["_problems"],
          "; ".join(good["_problems"][:2]))
    cites = all_cites(good)
    check("and every one of its citations is verbatim",
          bool(cites) and all(c["verified"] for c in cites),
          f'{sum(1 for c in cites if c["verified"])}/{len(cites)}')

    # The headline "N/N citations verified verbatim" is the number a reader
    # takes the page's word on, so it has to count everything the verifier
    # checked. Counted independently from the raw JSON, and the edge total is
    # asserted non-zero so the comparison cannot pass vacuously.
    raw = sum(len(x.get("cites") or []) for x in base["steps"])
    edge_cites = sum(len(ex.get("cites") or [])
                     for st in base["steps"] for ex in st.get("exits") or [])
    raw += edge_cites + sum(len(m.get("cites") or [])
                            for m in base.get("misconceptions") or [])
    check("the tally counts steps, transitions AND misconceptions",
          len(cites) == raw and edge_cites > 0,
          f"{len(cites)} counted / {raw} in the file, {edge_cites} on transitions")

    # Invariant 9. Two document kinds means a new way to verify the wrong thing:
    # route a primer through the ruling verifier and every primer-shaped key is
    # simply unread, producing a confident report about a document nobody wrote.
    from rules_cli import _kind
    check("an answer with no `kind` is a ruling",
          _kind({"holding": {}}, "x") == "ruling")
    check("`kind: primer` routes to the primer", _kind(base, "x") == "primer")
    misspelt = False
    try:
        _kind({"kind": "primmer"}, "x")
    except SystemExit:
        misspelt = True
    check("an unknown `kind` is refused, never defaulted", misspelt,
          "defaulting would silently route a typo down the ruling path")

    print("\n=== primer: a transition is a claim ===")
    # THE property this document kind rests on. An exit is what a reader acts
    # on at the table, so it may not be asserted more cheaply than a sentence
    # in a ruling: the default basis is `grounded`, and grounded needs a rule.
    naked = copy.deepcopy(base)
    naked["steps"][1]["exits"][0].pop("cites")
    r = verify_primer(naked, idx)
    check("an uncited transition fails verification",
          any("must cite the rule that says so" in p for p in r["_problems"]))

    ghost_edge = copy.deepcopy(base)
    ghost_edge["steps"][1]["exits"][0]["cites"] = [
        {"rule": "CR:999.9.z", "quote": "invented"}]
    r = verify_primer(ghost_edge, idx)
    check("a fabricated transition citation fails verification",
          bool(r["_problems"]) and any("999.9.z" in p for p in r["_problems"]))

    misquoted = copy.deepcopy(base)
    misquoted["steps"][1]["exits"][0]["cites"] = [
        {"rule": "CR:337.2", "quote": "the item resolves at the end of the turn"}]
    r = verify_primer(misquoted, idx)
    check("a transition quoting a real rule inexactly still fails",
          bool(r["_problems"]),
          "the rule exists; the words are not in it")

    declared = copy.deepcopy(base)
    declared["steps"][1]["exits"][0].pop("cites")
    declared["steps"][1]["exits"][0]["basis"] = "structural"
    r = verify_primer(declared, idx)
    check("but a transition may go uncited if it DECLARES itself structural",
          not r["_problems"], "; ".join(r["_problems"][:2]))
    # Invariant 4. The concession above must cost something visible, or it is a
    # free way to launder a guess: min() runs over transitions, not just steps.
    check("and the page then reports structural as its weakest link",
          r["_strength"] == "structural", f'-> {r["_strength"]}')

    # THE ONE THAT MATTERS MOST ON THIS PATH. `all()` over a generator
    # short-circuits, and these are not predicates — each call verifies a
    # citation and records the result on it. Stopping at the first False meant
    # a failing quote HID EVERY CITATION AFTER IT in the same block: a
    # fabrication two lines down was never checked and reported by nothing,
    # which is the exact failure this project exists to prevent.
    #
    # It surfaced as a KeyError in the renderer, on the `cite_as` that was
    # never set. The crash was the least of it.
    for where, place in (("a step", lambda a: a["steps"][0]),
                         ("a transition", lambda a: a["steps"][0]["exits"][0]),
                         ("a misconception", lambda a: a["misconceptions"][0])):
        hidden = copy.deepcopy(base)
        block = place(hidden)
        block["cites"] = [
            {"rule": "CR:333", "quote": "   "},                    # fails first
            {"rule": "CR:334.1", "quote": "a sentence nobody wrote"},   # must still be checked
        ]
        hr = safely(lambda hidden=hidden: verify_primer(hidden, idx),
                    {"_problems": []}, f"verify_primer: {where}")
        problems = hr.get("_problems", [])
        check(f"a failing citation in {where} does not hide the ones after it",
              any("empty once normalised" in p for p in problems)
              and any("not found verbatim" in p for p in problems),
              f"{len(problems)} problems: "
              + "; ".join(p[:44] for p in problems[:2]))
        # And the page must still render, since every cite was stamped.
        check(f"and every citation in {where} is stamped, so the page can render",
              bool(safely(lambda hr=hr: render(hr, idx), "", f"render: {where}")))

    print("\n=== primer: abstention is audited ===")
    # Invariant 8. Prose invites filling a gap from memory more than a ruling
    # does, so a primer's abstentions are held to the same standard.
    gap_step = copy.deepcopy(base)
    gap_step["steps"][2]["basis"] = "gap"
    gap_step["steps"][2].pop("rules_checked", None)
    r = verify_primer(gap_step, idx)
    check("a gap STEP must list rules_checked",
          any("gap step must list rules_checked" in p for p in r["_problems"]))

    gap_edge = copy.deepcopy(base)
    gap_edge["steps"][2]["exits"][0]["basis"] = "gap"
    r = verify_primer(gap_edge, idx)
    check("a gap TRANSITION must list rules_checked",
          any("gap transition must list rules_checked" in p for p in r["_problems"]))

    ghost_checked = copy.deepcopy(base)
    ghost_checked["steps"][2]["basis"] = "gap"
    ghost_checked["steps"][2]["rules_checked"] = ["CR:999.9.z"]
    r = verify_primer(ghost_checked, idx)
    check("rules_checked naming a rule that does not exist is refused",
          any("does not exist at this corpus version" in p for p in r["_problems"]))

    # The corpus stamp, considered_rejected and card rule_sections are verified
    # by helpers shared with the ruling path. Shared is not the same as pinned:
    # the primer calls them, and a call that goes missing is invisible to every
    # check filed under the other document. Same reasoning as the atomic-write
    # check below — a property nobody has watched fail on THIS path is not
    # pinned on it.
    shared = []
    stamp = copy.deepcopy(base)
    stamp["corpus"]["CR"] = "2025-01-01"
    shared.append(any("corpus.CR claims" in p
                      for p in verify_primer(stamp, idx)["_problems"]))
    ghost_cr = copy.deepcopy(base)
    ghost_cr["considered_rejected"] = [{"rule": "CR:9999", "why": "x"}]
    shared.append(any("does not exist at this corpus version" in p
                      for p in verify_primer(ghost_cr, idx)["_problems"]))
    tr_bare = copy.deepcopy(base)
    tr_bare["considered_rejected"] = [{"rule": "702.15", "why": "x"}]
    shared.append(any("exists only in TR" in p
                      for p in verify_primer(tr_bare, idx)["_problems"]))
    check("the shared provenance checks run on the primer path too",
          all(shared), f"corpus/rejected-id/TR-prefix: {shared}")

    # `rules_checked` is rendered with " · ".join(), which needs strings, and
    # the existence check str()s each ref for the lookup — so a list of plain
    # integers, which is the natural thing to write, verified clean and then
    # died in the renderer. The verifier certifying an answer it cannot render
    # is the two halves disagreeing about what a valid answer is.
    numeric = copy.deepcopy(base)
    numeric["steps"][0]["basis"] = "gap"
    numeric["steps"][0]["rules_checked"] = [332, 333]
    nr = verify_primer(numeric, idx)
    npage = safely(lambda: render(nr, idx), "", "render with numeric rules_checked")
    check("rules_checked written as numbers verifies AND renders",
          not nr["_problems"] and bool(npage) and "332 · 333" in npage,
          "; ".join(nr["_problems"][:2]) or "rendered")

    # --force exists to look at a document the verifier rejected, so every field
    # the renderer reads has to survive being absent — or the escape hatch
    # crashes on the only inputs anyone opens it for.
    bare = copy.deepcopy(base)
    bare["steps"][1].pop("heading")
    bare["steps"][1].pop("body")
    br = verify_primer(bare, idx)
    bpage = safely(lambda: render(br, idx), "", "render of a step with no heading")
    check("a step missing every optional field still renders under --force",
          len(br["_problems"]) >= 2 and bool(bpage),
          "; ".join(br["_problems"][:2]))

    # Every model-authored field, malformed. --force exists to look at exactly
    # these documents, so a renderer that crashes on them has no escape hatch
    # at all — and the crash replaces the problem list the author needs.
    #
    # Table-driven because these were found one at a time: heading, then body,
    # then rules_checked, then belief, then corpus. Fixing a class beats fixing
    # five instances and waiting for the sixth.
    malformations = {
        "a misconception with no belief": lambda a: a["misconceptions"][0].pop("belief"),
        "a misconception that is a string": lambda a: a["misconceptions"].insert(0, "x"),
        "misconceptions that are all strings": lambda a: a.__setitem__("misconceptions", ["a"]),
        "no corpus block at all": lambda a: a.pop("corpus"),
        "considered_rejected as bare strings": lambda a: a.__setitem__(
            "considered_rejected", ["CR:305"]),
        "open_questions as a bare string": lambda a: a.__setitem__("open_questions", "xyz"),
        "cards as a bare string": lambda a: a.__setitem__("cards", "Astral Heron"),
        "a step that is not an object": lambda a: a["steps"].append("junk"),
        "cites as a list of bare strings": lambda a: a["steps"][1]["exits"][0]
            .__setitem__("cites", ["CR:337.2"]),
        "a citation object with no rule": lambda a: a["steps"][1]["exits"][0]
            .__setitem__("cites", [{"quote": "x"}]),
        "cites as a bare string": lambda a: a["steps"][1].__setitem__("cites", "CR:337.1"),
        "corpus as a bare string": lambda a: a.__setitem__("corpus", "2026-07-16"),
        "considered_rejected with no why": lambda a: a.__setitem__(
            "considered_rejected", [{"rule": "CR:305"}]),
        "every one of them at once": lambda a: (
            a["misconceptions"].insert(0, "x"), a.pop("corpus"),
            a.__setitem__("cards", "X"), a["steps"][1].pop("heading")),
    }
    crashed = []
    for label, mutate in malformations.items():
        bad = copy.deepcopy(base)
        mutate(bad)
        try:
            got = verify_primer(bad, idx)
            render(got, idx)
            if not got["_problems"]:
                crashed.append(f"{label} (verified clean)")
        except Exception as exc:
            crashed.append(f"{label} ({type(exc).__name__})")
    check("every malformed field is reported, and --force still renders",
          not crashed, "; ".join(crashed[:3]))

    # A bare string where a list belongs is iterated one character at a time:
    # `"cards": "Astral Heron"` rendered twelve cards, each "not found".
    strung = copy.deepcopy(base)
    strung["cards"] = "Astral Heron"
    spage = safely(lambda: render(verify_primer(strung, idx), idx), "",
                   "render with cards as a string")
    check("nor is a string field iterated one character at a time",
          bool(spage) and spage.count("<figure") == 0,
          f'{spage.count("<figure")} cards rendered from a 12-character string')

    print("\n=== primer: the procedure has to be a procedure ===")
    import flowgraph as flowgraph_mod
    dangling = copy.deepcopy(base)
    dangling["steps"][1]["exits"][2]["goto"] = "s9"
    r = verify_primer(dangling, idx)
    check("a goto naming no step is refused",
          any("is not a step in this primer" in p for p in r["_problems"]),
          "the diagram is drawn from these, so it would point at nothing")

    orphan = copy.deepcopy(base)
    for s in orphan["steps"]:
        for ex in s.get("exits", []):
            if ex.get("goto") == "s4":
                ex["goto"] = "s5"
    r = verify_primer(orphan, idx)
    check("a step nothing reaches is refused",
          any("no run of this procedure reaches" in p for p in r["_problems"]))

    sealed = copy.deepcopy(base)
    for s in sealed["steps"]:
        for ex in s.get("exits", []):
            if ex.get("goto") is None:
                ex["goto"] = "s2"
    r = verify_primer(sealed, idx)
    check("a procedure with no way out is refused",
          any("no way out" in p for p in r["_problems"]))

    dupe = copy.deepcopy(base)
    dupe["steps"][2]["id"] = "s2"
    r = verify_primer(dupe, idx)
    check("duplicate step ids are refused",
          any("duplicate step id" in p for p in r["_problems"]),
          "every anchor is #<id>, so the second is unreachable")

    # A primer need not be a procedure at all — "the parts of a card" is a
    # legitimate linear explainer. The shape checks above must not fire on one,
    # or the only primers this skill can write are loops.
    linear = copy.deepcopy(base)
    for s in linear["steps"]:
        s.pop("exits", None)
    r = verify_primer(linear, idx)
    check("a linear primer with no transitions is still valid",
          not r["_problems"], "; ".join(r["_problems"][:2]))
    check("and draws no map, rather than a column of boxes with no arrows",
          safely(lambda: flowgraph_mod.svg(r["steps"]), None, "flowgraph.svg") == "")

    # Untrusted model JSON. Every access below assumes a dict; a list of bare
    # strings crashed the ruling path once and the traceback hid every problem
    # found after it. Reported and dropped, so the author sees the whole list.
    def malformed(mutate, phrase, name):
        """Verify a deliberately malformed primer; a crash fails the check.

        Catching here is the point. Without it the crash surfaced as
        "<suite crashed>" in the mutation battery — detected, but by a
        traceback rather than by the check whose whole job is to notice, and a
        check that only holds while the code is healthy is not a check.
        """
        bad = copy.deepcopy(base)
        mutate(bad)
        try:
            got = any(phrase in p for p in verify_primer(bad, idx)["_problems"])
        except Exception as exc:
            got = False
            note(f"verify_primer raised {type(exc).__name__}: {exc}")
        check(name, got)

    malformed(lambda a: a["steps"].append("s6"), "expected an object",
              "a step that is not an object is reported, not crashed")
    malformed(lambda a: a["steps"][1].__setitem__("exits", "s3"), "must be a list",
              "`exits` that is not a list of objects is reported, not crashed")
    # `id` is the page anchor, the goto target, and the key every later pass
    # subscripts. A step without one raised KeyError inside verification, so the
    # author got a traceback instead of the problem list.
    malformed(lambda a: a["steps"][2].pop("id"), "no `id`",
              "a step with no id is reported, not crashed")

    print("\n=== primer: the diagram cannot outrun the citations ===")
    import flowgraph
    import render_primer
    fresh = verify_primer(copy.deepcopy(base), idx)
    declared_exits = sum(len(s.get("exits") or []) for s in fresh["steps"])

    nodes, edges = safely(lambda: flowgraph.build(fresh["steps"]), ([], []),
                          "flowgraph.build")
    check("the graph has exactly one edge per declared transition",
          len(edges) == declared_exits and declared_exits > 0,
          f"{len(edges)} edges / {declared_exits} exits")
    check("and exactly one node per declared step",
          len(nodes) == len(fresh["steps"]), f"{len(nodes)} / {len(fresh['steps'])}")
    check("every edge lands on a step the primer declares",
          bool(edges) and all(e["to"] is None or 0 <= e["to"] < len(nodes)
                              for e in edges))

    page = safely(lambda: render(fresh, idx), "", "render_primer.render")
    drawn = sorted(int(n) for n in re.findall(r'class="fg-num"[^>]*>(\d+)</text>', page))
    written = sorted(int(n) for n in re.findall(r'class="exit-n">(\d+)</span>', page))
    check("every arrow on the map is numbered in the prose beside it",
          drawn == written and drawn == list(range(1, declared_exits + 1)),
          f"map {drawn} vs prose {written}")

    # The picture speaks the same language as the chips: a dashed arrow is a
    # move that follows from the rules cited rather than being written in one
    # place. Drawing a structural transition solid would overstate it on the
    # one surface a reader takes in at a glance; dashing a grounded one would
    # undersell every move the rules do state.
    plain = safely(lambda: flowgraph.svg(fresh["steps"]), "", "flowgraph.svg")
    check("an all-grounded primer draws no dashed arrow",
          bool(plain) and "stroke-dasharray" not in plain)
    soft = verify_primer(copy.deepcopy(base), idx)
    soft["steps"][1]["exits"][0]["basis"] = "structural"
    dashed = safely(lambda: flowgraph.svg(soft["steps"]), "", "flowgraph.svg")
    check("and a structural transition draws a dashed one",
          "stroke-dasharray" in dashed)

    mmd = safely(lambda: flowgraph.mermaid(fresh["steps"], fresh["topic"]), "",
                 "flowgraph.mermaid")
    ids = {"S_" + s["id"] for s in fresh["steps"]}
    used = set(re.findall(r"\bS_\w+", mmd))
    check("the mermaid export names only real steps", bool(used) and used <= ids,
          f"unknown: {sorted(used - ids)}")

    # A transition that cannot be placed is dropped from the SVG; the mermaid
    # path has to drop it too, or the text graph carries an edge the picture
    # refuses. "Names only real steps" cannot see this — a broken edge points at
    # DONE, and DONE is real.
    unplaceable = verify_primer(copy.deepcopy(base), idx)
    unplaceable["steps"][1]["exits"][2]["goto"] = "nowhere"
    _un_nodes, un_edges = safely(lambda: flowgraph.build(unplaceable["steps"]),
                                 ([], []), "flowgraph.build with a dangling goto")
    placeable = [e for e in un_edges if e["kind"] != "broken"]
    dangling_mmd = safely(lambda: flowgraph.mermaid(unplaceable["steps"], "T"), "",
                          "flowgraph.mermaid with a dangling goto")
    mmd_edges = len(re.findall(r"-\.?->\|", dangling_mmd))
    check("and drops the transitions it cannot place, as the picture does",
          len(placeable) > 0 and mmd_edges == len(placeable)
          and len(placeable) < len(un_edges),
          f"{mmd_edges} mermaid edges, {len(placeable)} placeable "
          f"of {len(un_edges)} declared")

    # The SVG is escaped by the page that embeds it; this export leaves the
    # project entirely, and Mermaid renders labels as HTML by default — so a
    # heading containing a tag becomes markup wherever the graph is finally
    # drawn. A newline is the quieter half: it ends the statement early and
    # truncates the graph, leaving something that still looks like a diagram.
    hostile = copy.deepcopy(fresh)
    hostile["steps"][0]["heading"] = '<img src=x>|"q"&\nsecond line'
    hostile["steps"][0]["exits"][0]["when"] = "a<b>c"
    hot = safely(lambda: flowgraph.mermaid(hostile["steps"], '<b>topic</b>'), "",
                 "flowgraph.mermaid")
    # Scoped to the label CONTENTS. Mermaid's own syntax is full of these
    # characters — `-->|"..."|`, `["..."]` — so scanning the whole file just
    # reports the language back at you. A label is what sits between the
    # quotes, and after escaping it holds none of them.
    labels = re.findall(r'"([^"]*)"', hot)
    header = hot.splitlines()[0] if hot else ""
    leaked = sorted({c for lab in labels + [header] for c in "<>|" if c in lab})
    check("the mermaid export escapes every label",
          len(labels) >= 2 and not leaked and "#lt;" in hot,
          f"{len(labels)} labels, leaked {leaked}")
    check("and collapses a newline rather than truncating the graph",
          bool(hot) and len(hot.splitlines()) == len(mmd.splitlines()),
          f"{len(hot.splitlines())} lines vs {len(mmd.splitlines())}")

    # `_mid` maps every non-alphanumeric character to "_", so it is not
    # injective: `s1.a` and `s1_a` both became S_s1_a, collapsing two declared
    # steps into one node and turning the transition between them into a
    # self-loop — in the export that exists so a diagram cannot outrun its
    # citations. Verification cannot see it, because the JSON ids ARE unique.
    collide = verify_primer(copy.deepcopy(base), idx)
    rename = {"s1": "x.a", "s2": "x_a"}
    for st in collide["steps"]:
        for ex in st.get("exits") or []:
            if ex.get("goto") in rename:
                ex["goto"] = rename[ex["goto"]]
        st["id"] = rename.get(st["id"], st["id"])
    cmmd = safely(lambda: flowgraph.mermaid(collide["steps"], "T"), "",
                  "flowgraph.mermaid with colliding ids")
    node_ids = re.findall(r"^  (S_\S+)\[", cmmd, re.M)
    check("the mermaid export gives every step its own node",
          len(node_ids) == len(collide["steps"]) == len(set(node_ids)),
          f"{len(node_ids)} node lines, {len(set(node_ids))} distinct")

    # A ruling and a primer about the same subject is the normal pairing, and
    # both slugs collapsed to reports/<topic>.html — so rendering one silently
    # destroyed the other.
    with tempfile.TemporaryDirectory() as d:
        pj, aj = os.path.join(d, "x-primer.json"), os.path.join(d, "x-answer.json")
        json.dump(base, open(pj, "w", encoding="utf-8"))
        json.dump(json.load(open(os.path.join(HERE, "heron-answer.json"),
                                 encoding="utf-8")), open(aj, "w", encoding="utf-8"))
        cli = os.path.join(HERE, "rules_cli.py")
        outs = []
        for source in (pj, aj):
            r = subprocess.run([sys.executable, cli, "report", source, "--no-open"],
                               capture_output=True, text=True, cwd=d)
            m = re.search(r"^report: (.+)$", r.stdout, re.M)
            outs.append(m.group(1) if m else "")
        check("a primer and a ruling on one subject do not overwrite each other",
              all(outs) and outs[0] != outs[1],
              " vs ".join(os.path.basename(o) for o in outs))
        for o in outs:
            if o and os.path.exists(o):
                os.remove(o)

    print("\n=== primer: the map tells the truth about itself ===")
    # A citation that failed the verbatim check drew a solid gold "grounded"
    # arrow a few hundred pixels above its own citation card reading ✗
    # UNVERIFIED. On a forced page the banner and the stamps were honest; the
    # diagram was the one element still claiming everything was fine.
    ghost_edge = copy.deepcopy(base)
    ghost_edge["steps"][0]["exits"][0]["cites"][0]["quote"] = "not in rule 336 at all"
    gr = verify_primer(ghost_edge, idx)
    gpage = safely(lambda: render(gr, idx), "", "render with a failed transition cite")
    gsvg = re.search(r'<svg class="flowgraph".*?</svg>', gpage or "", re.S)
    gsvg = gsvg.group(0) if gsvg else ""
    check("an unverified transition is drawn unmistakably, not as a confident arrow",
          bool(gr["_problems"]) and "fg-head-unverified" in gsvg
          and 'stroke="var(--mist-100)"' in gsvg
          and 'class="stamp bad"' in gpage,
          "it must separate in colour, weight and rhythm at once")

    # Two exits from one step to the next were both drawn at the spine's fixed
    # geometry — two identical lines, and two badges at identical coordinates
    # with an opaque fill, so the later painted out the earlier. One arrow for
    # two cited transitions: invariant 12's "no fewer" half, without --force.
    twin = copy.deepcopy(base)
    extra = copy.deepcopy(twin["steps"][0]["exits"][0])
    extra["when"] = "a second, different condition"
    twin["steps"][0]["exits"].insert(1, extra)
    tr = verify_primer(twin, idx)
    tpage = safely(lambda: render(tr, idx), "", "render with twin spine edges")
    spots = re.findall(r'<rect x="([-\d.]+)" y="([-\d.]+)"[^>]*/>'
                       r'<text[^>]*class="fg-num"', tpage or "")
    declared = sum(len(st.get("exits") or []) for st in tr["steps"])
    check("two transitions between the same pair of steps draw two arrows",
          not tr["_problems"] and len(spots) == declared
          and len(set(spots)) == declared,
          f"{len(spots)} badges at {len(set(spots))} distinct positions "
          f"for {declared} transitions")

    # A transition whose goto names no step keeps its number but cannot be
    # placed, and the accessible description went on counting it — a reader
    # using a screen reader was told about an arrow nobody can see.
    dangling = copy.deepcopy(base)
    dangling["steps"][1]["exits"][2]["goto"] = "s9"
    dr = verify_primer(dangling, idx)
    dsvg = safely(lambda: flowgraph.svg(dr["steps"]), "", "svg with a dangling goto")
    label = re.search(r'aria-label="([^"]*)"', dsvg or "")
    check("the map's description counts the arrows it actually drew",
          bool(label) and "11 transitions" in label.group(1)
          and "could not be drawn" in label.group(1),
          label.group(1)[:96] if label else "no aria-label")

    # A primer that declares transitions and can draw none of them used to lose
    # the whole map section, and its rail entry with it — silence that reads as
    # "this one has no diagram", which is a different document.
    allbad = copy.deepcopy(base)
    for st in allbad["steps"]:
        for ex in st.get("exits") or []:
            ex["goto"] = "nowhere"
    ab = verify_primer(allbad, idx)
    abpage = safely(lambda: render(ab, idx), "", "render with every goto broken")
    check("an undrawable map says so rather than disappearing",
          bool(ab["_problems"]) and 'id="map"' in abpage
          and "none of them could be drawn" in abpage,
          "the section and its rail entry both have to survive")

    print("\n=== primer: a primer is something a person reads ===")
    def flowgraph_max_steps():
        import render_primer as _rp
        return _rp.MAX_STEPS

    def hub(nsteps, per):
        cite = [{"rule": "CR:334", "quote": "Handle Outstanding Tasks"}]
        out = []
        for i in range(nsteps):
            exits = ([{"when": f"c{k}", "goto": f"h{nsteps - 1}", "cites": cite}
                      for k in range(per)] if i < nsteps - 1
                     else [{"when": "end", "cites": cite}])
            out.append({"id": f"h{i}", "heading": f"Step {i}", "body": "b",
                        "basis": "grounded", "cites": cite, "exits": exits})
        return out

    # Not a performance limit — the lane sweep lays out ten thousand
    # transitions in tens of milliseconds. A limit on what can still be a
    # primer: a hundred steps whose exits all target one common step needs a
    # gutter lane each, and the derived map comes out three hundred thousand
    # pixels wide. Nothing about that document is wrong under the citation gate,
    # which is why the refusal has to be a document rule.
    # Two independent limits, so two checks. One case that trips both proves
    # only that at least one works — and the first version of this used 100
    # steps x 20 exits, which trips both, so disabling the step cap alone left
    # it green.
    many_steps = copy.deepcopy(base)
    many_steps["steps"] = hub(flowgraph_max_steps() + 1, 1)
    msr = verify_primer(many_steps, idx)
    check("a document with too many steps to read as a map is refused",
          any("a person reads" in p for p in msr["_problems"]),
          f'{len(many_steps["steps"])} steps, '
          f'{sum(len(x.get("exits") or []) for x in many_steps["steps"])} transitions')

    many_edges = copy.deepcopy(base)
    many_edges["steps"] = hub(20, 12)
    mer = verify_primer(many_edges, idx)
    check("a document with too many transitions to draw is refused",
          any("gutter lanes" in p for p in mer["_problems"]),
          f'{len(many_edges["steps"])} steps, '
          f'{sum(len(x.get("exits") or []) for x in many_edges["steps"])} transitions')

    # The lane search was O(E x lanes) and lanes grow toward E when spans
    # overlap, so it was quadratic: 10,000 transitions took forty seconds
    # before a single byte of SVG. Replaced with a sweep; this is the property
    # that sweep has to preserve.
    lanes_ok, wide = True, hub(30, 6)
    fnodes, fedges = safely(lambda: flowgraph.build(wide), ([], []), "flowgraph.build")
    gutters = [e for e in fedges if e["kind"] in ("back", "skip", "self")]

    def _span(e):
        ys = [fnodes[e["from"]]["y"], fnodes[e["to"]]["y"]]
        return min(ys) - 6, max(ys) + flowgraph.BOX_H + 6

    by_lane = {}
    for e in gutters:
        by_lane.setdefault(e["lane"], []).append(_span(e))
    for spans in by_lane.values():
        spans.sort()
        for (a_top, a_bot), (b_top, _b) in zip(spans, spans[1:]):
            if b_top <= a_bot:
                lanes_ok = False
    check("no two transitions share a lane while their spans overlap",
          bool(gutters) and lanes_ok, f"{len(gutters)} gutter edges, "
          f"{len(by_lane)} lanes")

    print("\n=== primer: the procedure must be enterable ===")
    island = copy.deepcopy(base)
    for st in island["steps"]:
        for ex in st.get("exits") or []:
            if ex.get("goto") in ("s3", "s4") and st["id"] not in ("s3", "s4"):
                ex["goto"] = "s5"
    ir = verify_primer(island, idx)
    check("a disconnected island of steps is refused",
          any("no run of this procedure reaches" in p for p in ir["_problems"]),
          "two steps naming only each other each have an arrow arriving, so "
          '"is it named by anything" cannot see them')

    # A transition carries no id, so `item.get("id", "?")` reported every
    # transition-level rules_checked problem as `?:` — unattributable.
    unattributed = copy.deepcopy(base)
    unattributed["steps"][2]["exits"][0]["basis"] = "gap"
    unattributed["steps"][2]["exits"][0]["rules_checked"] = ["99999"]
    ur2 = verify_primer(unattributed, idx)
    check("a transition-level problem names the transition",
          any(re.match(r"s\d+ transition \d+: rules_checked names 99999", p)
              for p in ur2["_problems"]),
          "; ".join(p for p in ur2["_problems"] if "99999" in p)[:70])

    # Dropping a malformed step outright renumbered every step after it, so
    # every position reference in the surrounding prose pointed one place off
    # and the map quietly lost a box — recorded only in a list readers skim.
    slotted = copy.deepcopy(base)
    slotted["steps"][2] = "s3"
    # The VERIFY call is wrapped too, not only the render. A mutant that
    # removes the isinstance guard makes verification itself raise, and this
    # check was the one place still calling it bare — so the battery reported
    # "<suite crashed>" instead of the two checks that had already gone red by
    # name a few lines above.
    sl = safely(lambda: verify_primer(slotted, idx), {"_problems": [], "steps": []},
                "verify_primer with an unreadable step")
    slpage = safely(lambda: render(sl, idx), "", "render with an unreadable step")
    plates = re.findall(r'<div class="step-n"[^>]*>(\d+)</div>', slpage or "")
    check("an unreadable step keeps its slot rather than renumbering the rest",
          plates == [str(i) for i in range(1, len(base["steps"]) + 1)]
          and "could not be read" in (slpage or ""),
          f"plates {plates}")

    print("\n=== primer: the render gate ===")
    # Invariants 1 and 10. A primer has no disposition to downgrade, so the
    # only honest answer to a broken citation is to publish nothing.
    broken = copy.deepcopy(base)
    broken["steps"][0]["cites"] = [{"rule": "CR:999.9.z", "quote": "invented"}]
    with tempfile.TemporaryDirectory() as d:
        bad = os.path.join(d, "bad.json")
        out = os.path.join(d, "out.html")
        json.dump(broken, open(bad, "w", encoding="utf-8"))

        r = subprocess.run([sys.executable, os.path.join(HERE, "render_primer.py"), bad, out],
                           capture_output=True, text=True, cwd=HERE)
        check("a fabricated primer citation exits non-zero", r.returncode != 0,
              f"rc={r.returncode}")
        # Named so one mutant — removing the gate — proves both halves. They
        # are separate checks because "exited 1" and "wrote nothing" fail
        # independently: an atomic-write bug satisfies the first and not the second.
        check("and a fabricated primer citation leaves no page behind",
              not os.path.exists(out))

        r = subprocess.run([sys.executable, os.path.join(HERE, "rules_cli.py"), "graph", bad],
                           capture_output=True, text=True, cwd=HERE)
        check("`graph` refuses to emit a diagram for it too", r.returncode != 0,
              "a diagram handed to a website must not outrun the gate")

        r = subprocess.run([sys.executable, os.path.join(HERE, "render_primer.py"), bad, out,
                            "--force"], capture_output=True, text=True, cwd=HERE)
        forced = os.path.exists(out) and open(out, encoding="utf-8").read()
        check("--force renders the primer but marks the citation failed",
              bool(forced) and 'class="stamp bad"' in forced)
        check("--force says on the page that it must not be relied on",
              bool(forced) and 'class="forced"' in forced)

    # The banner is the only thing stopping a forced page from being mistaken
    # for a verified one, so it must answer "did this pass", not "did a quote
    # match". Scoped to citations, an uncited grounded step — which has no
    # citation to fail — produced a forced page with no banner at all.
    uncited = copy.deepcopy(base)
    uncited["steps"][0].pop("cites")
    ur = verify_primer(uncited, idx)
    upage = safely(lambda: render(ur, idx), "", "render of an uncited-step primer")
    check("a forced page is marked whatever kind of verification it failed",
          bool(ur["_problems"]) and 'class="forced"' in upage,
          "an uncited grounded step has no citation to fail")

    # A primer states no verdict, so the plate words must not appear on it. An
    # early draft reused the ruling template and shipped a primer headed
    # UNSETTLED, which reads as a failed answer rather than an explanation.
    # Invariant 10, on the primer's own write path. The code is the same shape
    # as the ruling's, which is exactly the reasoning this file exists to
    # refuse: a property nobody has watched fail on THIS path is not pinned on
    # it.
    #
    # The failure has to land on the WRITE, not before it. A first attempt
    # crashed render instead (by removing `corpus`) — which left the previous
    # page intact for the trivial reason that nothing was ever written, so the
    # check passed with an in-place write live underneath it. os.replace is
    # what fails here, so render and the temp write both succeed and the only
    # thing being tested is whether the destination was already truncated.
    #
    # Drives render_primer.main() rather than re-implementing the write, so
    # this tests that module and not this one.
    import render_primer as _rpw
    with tempfile.TemporaryDirectory() as d:
        kept = os.path.join(d, "primer.html")
        open(kept, "w", encoding="utf-8").write("PREVIOUS GOOD PRIMER")
        good_src = os.path.join(d, "p.json")
        json.dump(base, open(good_src, "w", encoding="utf-8"))
        _real_replace, _real_argv = os.replace, sys.argv
        try:
            os.replace = lambda *a, **k: (_ for _ in ()).throw(OSError("disk full"))
            sys.argv = ["render_primer.py", good_src, kept]
            try:
                _rpw.main()
            except BaseException:
                pass
        finally:
            os.replace, sys.argv = _real_replace, _real_argv
        check("a failed write leaves the previous primer intact",
              open(kept, encoding="utf-8").read() == "PREVIOUS GOOD PRIMER",
              "an in-place open() truncates the destination before it can fail")

    # A heading that does not fit its box. The first estimate was a flat
    # 6.15px/char, which is simply wrong for a proportional face: an ordinary
    # 42-character heading measured 279px in a 262px box and one set in caps
    # measured 537px, running out over the transition arrows beside it.
    wide = copy.deepcopy(base)
    for i, heading in enumerate(["W" * 42, "M" * 42,
                                 "Handling Outstanding Tasks Before Anything",
                                 "i" * 42, "R — Resolve"]):
        if i < len(wide["steps"]):
            wide["steps"][i]["heading"] = heading
    wsvg = safely(lambda: flowgraph.svg(verify_primer(wide, idx)["steps"]), "",
                  "flowgraph.svg with wide headings")
    # Measured with the harness's OWN table, deliberately duplicated from the
    # browser measurements rather than imported. Calling flowgraph._char_w here
    # made the check circular: a mutant that flattened every glyph to one
    # average width also flattened the yardstick, so 42 characters at 6.15px
    # "fit" a box they visibly overflow. A check has to be an independent
    # oracle or it only ever confirms the code agrees with itself.
    def ref_w(ch):
        if ch == " ":
            return 3.3
        if ch in "iljI.,;:'!|()[]{}/\\`":
            return 4.4
        if ch in "WM":
            return 12.8
        if ch in "—–":
            return 11.6
        return 8.6 if ch.isdigit() else (10.1 if ch.isupper() else 7.6)

    room = flowgraph.BOX_W - flowgraph.PAD_X - 20 - 14
    drawn_labels = re.findall(r'class="fg-step"[^>]*>([^<]*)</text>', wsvg)
    too_wide = [lab for lab in drawn_labels if sum(ref_w(c) for c in lab) > room]
    check("a step heading is clipped to fit inside its box",
          len(drawn_labels) >= 5 and not too_wide,
          f"{len(drawn_labels)} labels, over by: {[lab[:12] for lab in too_wide]}")
    # Belt AND braces: the estimate is measured against a font the reader may
    # not have, so the label is also cut geometrically at the box edge.
    check("and is cut at the box edge even if the estimate is wrong",
          'clipPath id="fg-box"' in wsvg and 'clip-path="url(#fg-box)"' in wsvg)

    # A two-digit transition number in an 18px box printed with its second
    # digit on the border. Found on paper, where the box is a hairline rule and
    # nothing hides it; checked here so it does not have to be found there again.
    badges = re.findall(r'<rect x="([-\d.]+)" y="[-\d.]+" width="(\d+)"[^>]*/>'
                        r'<text x="([-\d.]+)"[^>]*class="fg-num"[^>]*>(\d+)</text>', plain)
    narrow = [n for x, w, _tx, n in badges if int(w) < 11 + 7 * len(n) and len(n) > 1]
    check("every transition badge is wide enough for its own number",
          bool(badges) and not narrow,
          f"{len(badges)} badges, too narrow: {narrow}")

    # Print is invisible to every other gate, and the diagram is the part of a
    # primer most likely to survive as paper on a judge's table. The whole print
    # inversion works by remapping CSS custom properties, so a colour written as
    # a literal anywhere in the SVG keeps its dark-ground value on white — the
    # defect that once printed the grounded half of a verdict line at 2.23:1.
    # flowgraph emits colour ONLY as tokens; this is the check that keeps it so.
    literals = re.findall(r'(?:fill|stroke)="(#[0-9a-fA-F]{3,8}|rgba?\([^"]*\))"', plain)
    check("the diagram writes no colour the print sheet cannot remap",
          bool(plain) and not literals, f"literals: {sorted(set(literals))[:4]}")
    check("and the primer's own print sheet inverts the map with the page",
          "@media print" in render_primer._PRIMER_CSS
          and ".fg-step" in render_primer._PRIMER_CSS[
              render_primer._PRIMER_CSS.index("@media print"):])

    # A step's number is its position, in all three places it appears: the
    # plate, the diagram box, and every transition pointing at it. Deriving it
    # from digits in the id agreed with position for s1..s5 and parted company
    # the moment an author wrote s0 — the plate said 1, the links said 0.
    #
    # Checked against ids carrying no digits at all, so a number can only have
    # come from position. Every rendered link is then compared to the position
    # of the step it actually points at, which is a claim about each link
    # rather than about the page containing some digit somewhere.
    renamed = verify_primer(copy.deepcopy(base), idx)
    mapping = {s["id"]: "z" + chr(97 + i) for i, s in enumerate(renamed["steps"])}
    for st in renamed["steps"]:
        for ex in st.get("exits") or []:
            if ex.get("goto"):
                ex["goto"] = mapping[ex["goto"]]
        st["id"] = mapping[st["id"]]
    renamed["_weakest"] = mapping.get(renamed["_weakest"], renamed["_weakest"])
    position = {st["id"]: i + 1 for i, st in enumerate(renamed["steps"])}

    rpage = safely(lambda: render(renamed, idx), "", "render with non-numeric step ids")
    # Digits only: the weakest-step metric renders "step 1</a>" with no heading
    # after it, and \S+ swallowed the closing tag into the number.
    links = re.findall(r'href="#(z[a-z])">step\s+(\d+)', rpage)
    wrong = [(t, n) for t, n in links if n != str(position.get(t))]
    check("every link numbers the step it points at by position",
          len(links) >= len(renamed["steps"]) and not wrong,
          f"{len(links)} links, wrong: {wrong[:3]}")
    check("and no step number is rendered unknown",
          bool(rpage) and "step ?" not in rpage)

    # `bool(page)` is load-bearing: `safely`'s "" fallback satisfies any
    # negative assertion, so this passed with render entirely broken while its
    # neighbours correctly went red.
    check("a primer prints no disposition word",
          bool(page) and not re.search(r'class="disp\b', page)
          and 'class="verdict ' not in page)
    # min() runs over transitions as well as steps, so the weakest thing is
    # often not a step at all — and filing its basis under its SOURCE step made
    # the page contradict itself: "Weakest step 2 · structural" linking to a
    # plate whose own chip read "● grounded", with the structural thing named
    # nowhere. The label has to say what it is pointing at.
    #
    # This replaces a check that asserted the literal words "Weakest step",
    # which was both the wrong property and case-sensitively vacuous — the page
    # already said "the lowest link, never an average" two lines below it.
    soft = copy.deepcopy(base)
    soft["steps"][1]["exits"][0].pop("cites", None)
    soft["steps"][1]["exits"][0]["basis"] = "structural"
    sr = verify_primer(soft, idx)
    spage = safely(lambda: render(sr, idx), "", "render with a structural transition")
    check("the weakest link names what is actually weakest",
          sr["_strength"] == "structural"
          and str(sr.get("_weakest_label", "")).startswith("transition")
          and bool(spage) and sr["_weakest_label"] in spage,
          f'{sr["_strength"]} / {sr.get("_weakest_label")!r}')
    check("and still anchors at the step a reader has to open",
          bool(spage) and f'href="#{sr["_weakest"]}"' in spage
          and sr["_weakest"] in {st["id"] for st in sr["steps"]})


def shipped_primers(idx):
    """Every primer this skill ships still verifies against the current corpus.

    This is the check a rules update is run for. A renumbering — Movement
    440->445, Scoring 462-467->467-472 in the 2026-07-16 update — silently
    invalidates citations in a committed document, and the shipped primers are
    the ones a reader is most likely to open first. Each is asserted whole:
    every citation verbatim, the transitions still form a procedure, and the
    derived export still matches.
    """
    print("\n=== the shipped primers ===")
    import glob
    import fireworks_ir
    import flowgraph
    from render_primer import all_cites, render, verify_primer

    found = sorted(glob.glob(os.path.join(HERE, "*-primer.json")))
    check("the skill ships primers at all", bool(found),
          "a primer nobody wrote is a format nobody uses")
    for path in found:
        name = os.path.basename(path).replace("-primer.json", "")
        ans = verify_primer(json.load(open(path, encoding="utf-8")), idx)
        cites = all_cites(ans)
        ok = check(f"{name}: verifies clean against this corpus",
                   not ans["_problems"] and bool(cites)
                   and all(c["verified"] for c in cites),
                   "; ".join(ans["_problems"][:2])
                   or f'{len(cites)} citations, all verbatim')
        if not ok:
            check(f"{name}: transition agreement was checked", False,
                  "skipped — this primer did not verify, so nothing downstream "
                  "of it was compared")
            continue
        page = safely(lambda: render(ans, idx), "", f"{name}: render")
        _nodes, edges = safely(lambda: flowgraph.build(ans["steps"]), ([], []),
                               f"{name}: flowgraph.build")
        drawn = [e for e in edges if e["kind"] != "broken"]
        ir = safely(lambda: fireworks_ir.build(ans), {"arrows": []},
                    f"{name}: fireworks_ir.build")
        written = sorted(int(n) for n in
                         re.findall(r'class="exit-n">(\d+)</span>', page))
        # `len(drawn) > 0` is the whole check. Without it this compared three
        # `safely` fallbacks against each other: break flowgraph.build and all
        # three primers reported "0 in prose, 0 on the map, 0 exported" and
        # PASSED — the group docs/maintaining.md names as the thing a rules
        # update is run for, asserting nothing.
        check(f"{name}: the report, the map and the export agree on every transition",
              len(drawn) > 0
              and written == sorted(e["n"] for e in drawn)
              == sorted(int(a["label"]) for a in ir["arrows"]),
              f'{len(written)} in prose, {len(drawn)} on the map, '
              f'{len(ir["arrows"])} exported')


def committed_diagrams(idx):
    """A shipped diagram must still be the one this code and corpus produce.

    `data/diagrams/` holds rendered pictures so they are ready to use without a
    Fireworks install — which means they are a copy, and a copy drifts. The
    same failure the rulebook has a check for: a shipped artifact that no
    longer matches its generator goes on looking current, and here it would go
    on asserting a procedure the rules have since renumbered.

    The IR is compared, not the SVG: the IR is what this project derives and
    stands behind, while the SVG is Fireworks' rendering of it and would differ on
    any version bump of theirs. Maintainer-side only — a standalone install has
    no repo around it and nothing to compare.
    """
    print("\n=== committed diagrams ===")
    import glob
    import fireworks_ir
    from render_primer import verify_primer

    # INSIDE the skill folder. These first went to docs/diagrams/, which put
    # them out of reach of the mutation battery — it sandboxes the skill — and
    # out of reach of anyone who copies the folder, which ADR 0004 says is the
    # product. One location, shipped with the thing it describes.
    shipped = os.path.join(HERE, "..", "data", "diagrams")
    shipped = os.path.normpath(shipped)
    if not check("the shipped diagrams directory is present", os.path.isdir(shipped),
                 "a primer whose diagram is not shipped is a diagram nobody has"):
        return

    stale = []
    seen = set()
    for path in sorted(glob.glob(os.path.join(HERE, "*-primer.json"))):
        name = os.path.basename(path).replace("-primer.json", "")
        committed = os.path.join(shipped, f"{name}.fireworks.json")
        svg = os.path.join(shipped, f"{name}.svg")
        seen.update({os.path.basename(committed), os.path.basename(svg)})
        if not os.path.exists(committed):
            stale.append(f"{name}: never committed")
            continue
        ans = safely(lambda path=path: verify_primer(
            json.load(open(path, encoding="utf-8")), idx), None, f"{name}: verify")
        if ans is None:
            stale.append(f"{name}: could not be verified at all")
            continue
        # `{}` and not None: the fallback is iterated two lines down, so a
        # generator that raises would have swapped one crash for another.
        fresh = safely(lambda ans=ans: fireworks_ir.build(ans), {},
                       f"{name}: fireworks_ir.build")
        # The one unguarded load in this group. A committed file truncated to
        # `{"nodes": [` took the whole suite down with a JSONDecodeError — two
        # later groups never ran and no summary line printed, which under the
        # battery reads as "<suite crashed>": the exact outcome guarding these
        # exists to eliminate.
        saved = safely(lambda: json.load(open(committed, encoding="utf-8")), None,
                       f"{name}: reading the committed IR")
        if saved is None:
            stale.append(f"{name}: committed IR is unreadable")
        elif not fresh:
            stale.append(f"{name}: could not be regenerated at all")
        elif fresh != saved:
            diffs = [k for k in set(fresh) | set(saved) if fresh.get(k) != saved.get(k)]
            stale.append(f"{name}: {', '.join(sorted(diffs))} differ")

        # The IR is compared above because it is what this project derives. The
        # SVG was compared by NOTHING — a blank one passed, and so did an orphan
        # pair with no primer behind it. Not a full render comparison, which
        # would break on any Fireworks version bump; the two questions the
        # committed picture must answer for itself.
        if not os.path.exists(svg):
            stale.append(f"{name}: no rendered diagram beside its IR")
        else:
            body = safely(lambda svg=svg: open(svg, encoding="utf-8").read(), "",
                          f"{name}: reading the committed SVG")
            labels = [int(a["label"]) for a in (fresh or {}).get("arrows", [])]
            complaint = diagram_complaint(body, labels)
            if complaint:
                stale.append(f"{name}: {complaint}")

    orphans = sorted(f for f in os.listdir(shipped)
                     if f not in seen and not f.startswith("."))
    if orphans:
        stale.append("no primer behind: " + ", ".join(orphans[:4]))

    # The judgement itself, against synthetic input. Corrupting a real committed
    # diagram would exercise this too, but no mutant can corrupt a data file, so
    # that path pinned nothing.
    whole = '<svg><text class="fg-num" fill="x">1</text>' \
            '<text class="fg-num" fill="x">2</text></svg>'
    check("a truncated committed SVG is detected",
          diagram_complaint(whole[:20], [1, 2]) == "the committed SVG is truncated",
          repr(diagram_complaint(whole[:20], [1, 2])))
    check("a blank committed SVG is detected",
          diagram_complaint("", [1, 2]) is not None)
    check("a committed SVG drawing different arrows from its IR is detected",
          "draws" in (diagram_complaint(whole, [1, 2, 3]) or ""),
          repr(diagram_complaint(whole, [1, 2, 3])))
    check("and a whole one agreeing with its IR is not",
          diagram_complaint(whole, [1, 2]) is None,
          repr(diagram_complaint(whole, [1, 2])))

    check("every committed diagram matches what this corpus now produces",
          not stale, "; ".join(stale[:3])
          or "regenerate with `rules_cli.py graph <primer> ../data/diagrams/<name>.svg`")


def fireworks_export(idx):
    """The exported diagram, which travels away from the citations that back it.

    Invariant 12 does not stop at the report. A Fireworks SVG ends up on a
    website, in a deck, on a phone — everywhere the prose and the ✓ VERIFIED
    stamps are not. It is derived from the same `flowgraph.build` the in-report
    map is, and these assert the derivation survives the trip in both
    directions: nothing drawn that was not declared, nothing declared that is
    not drawn.

    The IR is what this project produces and stands behind. Fireworks itself
    lives outside the skill folder, so nothing here may require it.
    """
    print("\n=== primer: the exported diagram ===")
    import copy
    import tempfile
    import fireworks_ir
    import flowgraph
    from render_primer import verify_primer

    src = os.path.join(HERE, "hot-fepr-primer.json")
    if not check("the primer fixture is present for the export checks",
                 os.path.exists(src)):
        return
    base = json.load(open(src, encoding="utf-8"))
    ans = verify_primer(copy.deepcopy(base), idx)
    ir = safely(lambda: fireworks_ir.build(ans), {"nodes": [], "arrows": [], "legend": [],
                                                  "subtitle": ""}, "fireworks_ir.build")
    nodes, edges = safely(lambda: flowgraph.build(ans["steps"]), ([], []),
                          "flowgraph.build")
    drawn = [e for e in edges if e["kind"] != "broken"]
    step_ids = {s["id"] for s in ans["steps"]}
    ir_ids = {n["id"] for n in ir["nodes"]}

    check("every node in the export is a declared step",
          ir_ids - {fireworks_ir._END_ID} == step_ids,
          f"extra: {sorted(ir_ids - step_ids - {fireworks_ir._END_ID})}")
    check("every arrow in the export is a declared transition, and none is missing",
          len(ir["arrows"]) == len(drawn) and len(drawn) > 0,
          f'{len(ir["arrows"])} arrows / {len(drawn)} drawable transitions')
    check("and every arrow joins two nodes the export declares",
          bool(ir["arrows"])
          and all(a["source"] in ir_ids and a["target"] in ir_ids for a in ir["arrows"]))

    # The number on the exported arrow is the number in the prose. They come
    # from one counter in flowgraph, and this is what keeps them from drifting
    # if a second one is ever introduced.
    exported = sorted(int(a["label"]) for a in ir["arrows"])
    # A transition whose goto names no step keeps its NUMBER but cannot be
    # placed. The export must omit the arrow and leave every other number
    # where it was — drawing it would put a move on the picture that the
    # document itself could not locate, and renumbering would break the one
    # thing tying the picture to the prose.
    dangling = copy.deepcopy(base)
    dangling["steps"][1]["exits"][2]["goto"] = "nowhere"
    dr = verify_primer(dangling, idx)
    dir_ = safely(lambda: fireworks_ir.build(dr), {"arrows": []},
                  "fireworks_ir.build with a dangling goto")
    d_labels = sorted(int(a["label"]) for a in dir_["arrows"])
    check("a transition that cannot be placed is not exported, and renumbers nothing",
          len(d_labels) == len(drawn) - 1 and 5 not in d_labels
          and d_labels == [n for n in range(1, len(drawn) + 1) if n != 5],
          f"exported {d_labels}")

    check("the exported arrows carry the same numbers as the prose",
          bool(exported) and exported == sorted(e["n"] for e in drawn),
          f"{exported[:6]}…")

    # Fireworks names its edge classes by role; this project names them by
    # basis. A basis with no mapping would silently fall through to "neutral" —
    # the class this diagram's own legend calls "the rules do not settle it".
    from render_report import RANK
    check("every basis maps to an edge class, so none silently reads as a gap",
          set(RANK) <= set(fireworks_ir.FLOW_FOR_BASIS),
          f"unmapped: {sorted(set(RANK) - set(fireworks_ir.FLOW_FOR_BASIS))}")

    # A failed citation must not travel as a confident arrow. The in-report map
    # inverts it; the export has to say so too, in Fireworks' own vocabulary.
    broken = copy.deepcopy(base)
    broken["steps"][0]["exits"][0]["cites"][0]["quote"] = "not in rule 336 at all"
    br = verify_primer(broken, idx)
    bir = safely(lambda: fireworks_ir.build(br), {"arrows": [], "legend": []},
                 "fireworks_ir.build with a failed cite")
    flows = {a["id"]: a["flow"] for a in bir["arrows"]}
    check("an unverified transition is exported in the failed class, not its declared one",
          flows.get("t1") == fireworks_ir.FLOW_UNVERIFIED
          and any(r["flow"] == fireworks_ir.FLOW_UNVERIFIED for r in bir["legend"]),
          f'transition 1 exported as {flows.get("t1")!r}')

    # Same rule as the report's basis key: a legend row for a style that does
    # not appear is a line the reader holds for nothing.
    check("the legend lists only the edge classes actually drawn",
          bool(ir["legend"])
          and {r["flow"] for r in ir["legend"]} == {a["flow"] for a in ir["arrows"]},
          f'legend {[r["flow"] for r in ir["legend"]]}')

    # This artifact leaves the report behind, so it has to carry its own
    # provenance — which corpus, and that it is unofficial.
    corpus_version = (ans.get("corpus") or {}).get("CR", "")
    # `"" in anything` is True, so an absent corpus.CR made this pass on a
    # subtitle carrying no version at all.
    check("the exported diagram carries its corpus version and says it is unofficial",
          bool(corpus_version) and corpus_version in ir["subtitle"]
          and "unofficial" in ir["subtitle"],
          ir["subtitle"][:70])

    # Found by sweeping every guard and deleting it: 25 of 59 could be removed
    # with the whole suite still green. Most were display paths; these are the
    # ones whose removal would change what the tool ACCEPTS. None was masked —
    # they were simply never on a path any check walked, which is the quieter
    # half of the same blind spot.
    cli = os.path.join(HERE, "rules_cli.py")
    with tempfile.TemporaryDirectory() as d:
        ruling = os.path.join(d, "r-answer.json")
        json.dump(json.load(open(os.path.join(HERE, "heron-answer.json"),
                                 encoding="utf-8")),
                  open(ruling, "w", encoding="utf-8"))
        run = subprocess.run([sys.executable, cli, "graph", ruling],
                             capture_output=True, text=True, cwd=d)
        check("`graph` refuses a ruling, which has no step graph",
              run.returncode != 0 and "needs a primer" in (run.stdout + run.stderr),
              f"rc={run.returncode}")

        primer_path = os.path.join(d, "p-primer.json")
        json.dump(base, open(primer_path, "w", encoding="utf-8"))
        run = subprocess.run([sys.executable, cli, "graph", primer_path,
                              "--format=svg"], capture_output=True, text=True, cwd=d)
        check("an unknown --format is refused rather than silently defaulted",
              run.returncode != 0
              and "unknown --format" in (run.stdout + run.stderr)
              and not [f for f in os.listdir(d) if f.endswith((".svg", ".json"))
                       if f not in ("p-primer.json", "r-answer.json")],
              f"rc={run.returncode}")

        # Invariant 9. A relative input that does not exist must be refused, not
        # quietly resolved against the skill folder — where a same-named shipped
        # sample would be verified instead, and reported as the caller's answer.
        run = subprocess.run([sys.executable, cli, "verify", "hot-fepr-primer.json"],
                             capture_output=True, text=True, cwd=d)
        check("a relative input that is not there is refused, not substituted",
              run.returncode != 0 and "no such answer file" in (run.stdout + run.stderr),
              "the skill ships a file of that name; resolving to it would verify "
              "a document the caller never wrote")

    # Shape guards on the document itself, none of which any check reached.
    malformed_shapes = {
        "steps that are not a list": (lambda a: a.__setitem__("steps", "s1"),
                                      "at least one step"),
        "no steps at all": (lambda a: a.__setitem__("steps", []), "at least one step"),
        "a step with an unknown basis": (
            lambda a: a["steps"][0].__setitem__("basis", "definitional"), "unknown basis"),
        "a transition with no condition": (
            lambda a: a["steps"][0]["exits"][0].pop("when"), "no `when`"),
        # Whitespace is truthy, so `if not s.get("heading")` passed a heading of
        # spaces. The guard was fixed and this table was not, so the mutant
        # reverting it survived — the fix was real and pinned by nothing.
        "a heading that is only whitespace": (
            lambda a: a["steps"][0].__setitem__("heading", "   "), "no heading"),
        "a body that is only whitespace": (
            lambda a: a["steps"][0].__setitem__("body", "  \n "), "no body"),
    }
    missed = []
    for label, (mutate, phrase) in malformed_shapes.items():
        bad = copy.deepcopy(base)
        mutate(bad)
        got = safely(lambda bad=bad: verify_primer(bad, idx), {"_problems": []},
                     f"verify_primer: {label}")
        if not any(phrase in p for p in got.get("_problems", [])):
            missed.append(f"{label} (wanted {phrase!r})")
    check("every malformed document shape is reported by name",
          not missed, "; ".join(missed))

    print("\n=== primer: the export refuses what the report refuses ===")
    with tempfile.TemporaryDirectory() as d:
        bad = os.path.join(d, "bad-primer.json")
        json.dump(broken, open(bad, "w", encoding="utf-8"))
        for fmt in ("fireworks", "mermaid"):
            run = subprocess.run([sys.executable, cli, "graph", bad, f"--format={fmt}"],
                                 capture_output=True, text=True, cwd=d)
            wrote = [f for f in os.listdir(d) if f != "bad-primer.json"]
            check(f"`graph --format={fmt}` refuses an unverified primer",
                  run.returncode != 0 and not wrote,
                  f"rc={run.returncode}, wrote {wrote}")
            for f in wrote:
                os.remove(os.path.join(d, f))

    # The renderer is NOT ours, and it may do anything on the way out. A stub
    # that writes half a file and exits 1 left a 36-byte fragment where a
    # 19,868-byte diagram had been, and the destination then looked like an
    # artifact — invariant 10, on a path the ruling and primer renderers had
    # already been taught to protect.
    #
    # Driven with a stub rather than the real Fireworks, deliberately: the
    # property is "however the renderer fails, the previous diagram survives",
    # and the real one cannot be made to fail on demand.
    import stat
    with tempfile.TemporaryDirectory() as d:
        primer = os.path.join(d, "ok-primer.json")
        json.dump(base, open(primer, "w", encoding="utf-8"))
        keep = os.path.join(d, "kept.svg")
        open(keep, "w", encoding="utf-8").write("PREVIOUS GOOD DIAGRAM")

        stub_home = os.path.join(d, "stub")
        os.makedirs(os.path.join(stub_home, "scripts"))
        stub = os.path.join(stub_home, "scripts", "fireworks.py")
        open(stub, "w", encoding="utf-8").write(
            "import sys\n"
            "open(sys.argv[-1], 'w').write('<svg>PARTIAL')\n"
            "print('{\"ok\": false, \"error\": \"renderer exploded\"}')\n"
            "sys.exit(1)\n")
        os.chmod(stub, os.stat(stub).st_mode | stat.S_IEXEC)

        run = subprocess.run(
            [sys.executable, cli, "graph", primer, keep],
            capture_output=True, text=True, cwd=d,
            env=dict(os.environ, RIFTBOUND_FIREWORKS=stub_home))
        # Read defensively. Rendering straight over the destination and then
        # discarding the wreckage DELETES it, so a bare open() raised here and
        # the battery reported "<suite crashed>" instead of this check going
        # red by name — the third time in this work that a check crashed on the
        # exact failure it exists to watch for.
        survived = (open(keep, encoding="utf-8").read()
                    if os.path.exists(keep) else "<destination was destroyed>")
        check("a failed render leaves the previous diagram untouched",
              run.returncode != 0 and survived == "PREVIOUS GOOD DIAGRAM",
              f"rc={run.returncode}, destination now {survived[:26]!r}")
        check("and clears up after itself rather than leaving a staging file",
              not [f for f in os.listdir(d) if f.endswith(".rendering")],
              f'{[f for f in os.listdir(d) if f.endswith(".rendering")]}')
        # The IR is the artifact this project stands behind, so it is written
        # even when the picture could not be.
        check("and the IR it wrote is still there to render later",
              os.path.exists(os.path.join(d, "kept.fireworks.json")))

    # Edge shapes the shipped primers do not exercise. The exit node's id is
    # minted HERE rather than taken from the document, so a primer that happens
    # to declare that id produced an IR with two nodes sharing one — and it
    # verified clean, because the collision does not exist in the document.
    # Same failure as `_mid` collapsing two step ids in the mermaid export.
    cite = [{"rule": "CR:334", "quote": "Handle Outstanding Tasks"}]
    shapes = {
        "a step named like the exit node": [
            {"id": fireworks_ir._END_ID, "heading": "A", "body": "b",
             "basis": "grounded", "cites": cite,
             "exits": [{"when": "done", "cites": cite}]}],
        "a single step that only exits": [
            {"id": "s1", "heading": "Only", "body": "b", "basis": "grounded",
             "cites": cite, "exits": [{"when": "done", "cites": cite}]}],
        "a single step that loops to itself": [
            {"id": "s1", "heading": "Only", "body": "b", "basis": "grounded",
             "cites": cite, "exits": [{"when": "again", "goto": "s1", "cites": cite},
                                      {"when": "done", "cites": cite}]}],
        "a linear primer with no transitions": [
            {"id": "s1", "heading": "A", "body": "b", "basis": "grounded", "cites": cite},
            {"id": "s2", "heading": "B", "body": "b", "basis": "grounded", "cites": cite}],
    }
    broken_shapes = []
    for label, steps in shapes.items():
        shaped = copy.deepcopy(base)
        shaped["steps"] = steps
        ir_shape = safely(lambda shaped=shaped: fireworks_ir.build(
            verify_primer(shaped, idx)), None, f"fireworks_ir.build: {label}")
        if ir_shape is None:
            broken_shapes.append(f"{label}: raised")
            continue
        node_ids = [n["id"] for n in ir_shape["nodes"]]
        if len(node_ids) != len(set(node_ids)):
            broken_shapes.append(f"{label}: two nodes share an id")
        dangling = [a for a in ir_shape["arrows"]
                    if a["source"] not in node_ids or a["target"] not in node_ids]
        if dangling:
            broken_shapes.append(f"{label}: {len(dangling)} arrow(s) point at no node")
    check("the export survives shapes the shipped primers do not have",
          not broken_shapes, "; ".join(broken_shapes[:3]))

    # TWO GATES GUARD THIS PATH, AND EACH MASKED THE OTHER. `cmd_report` refuses
    # a document with problems, and then the renderer it shells out to refuses
    # again. Delete `cmd_report`'s entirely and the whole suite stays green,
    # because the renderer catches what it let through — so the gate whose own
    # docstring calls it "the ONLY way to finish an answer" was pinned by
    # nothing at all.
    #
    # A one-at-a-time mutation battery cannot see this: redundant guards are
    # good for safety and invisible to it, and it reports both as covered.
    # The answer is a check per guard, written so it can tell WHICH one fired —
    # the two announce themselves differently, so the message says who refused.
    with tempfile.TemporaryDirectory() as d:
        for label, source, gate in (
                ("primer", base, "not rendering"),
                ("ruling", json.load(open(os.path.join(HERE, "heron-answer.json"),
                                          encoding="utf-8")), "not rendering")):
            broken_doc = copy.deepcopy(source)
            if label == "primer":
                broken_doc["steps"][0]["cites"] = [{"rule": "CR:999.9.z", "quote": "invented"}]
            else:
                broken_doc["notes"][0]["cites"] = [{"rule": "CR:999.9.z", "quote": "invented"}]
            bad_doc = os.path.join(d, f"{label}-answer.json")
            json.dump(broken_doc, open(bad_doc, "w", encoding="utf-8"))
            run = subprocess.run([sys.executable, cli, "report", bad_doc, "--no-open"],
                                 capture_output=True, text=True, cwd=d)
            check(f"`report` refuses a broken {label} at its OWN gate",
                  run.returncode != 0 and gate in run.stdout
                  and "refusing to render" not in (run.stderr or ""),
                  "the renderer's gate must not be what caught it — that is the "
                  "masking this check exists to expose")

    # Same shape, one layer down: `verify`'s exit code is its whole contract,
    # and nothing else on that path would notice if it stopped meaning anything.
    with tempfile.TemporaryDirectory() as d:
        broken_doc = copy.deepcopy(base)
        broken_doc["steps"][0]["cites"] = [{"rule": "CR:999.9.z", "quote": "invented"}]
        bad_doc = os.path.join(d, "v-primer.json")
        json.dump(broken_doc, open(bad_doc, "w", encoding="utf-8"))
        run = subprocess.run([sys.executable, cli, "verify", bad_doc],
                             capture_output=True, text=True, cwd=d)
        check("`verify` reports a broken primer through its exit code",
              run.returncode != 0 and "999.9.z" in run.stdout,
              f"rc={run.returncode}")

    # The exit code is not the artifact. A renderer that writes `<svg><g>` and
    # exits 0 was announced as "wrote out.svg" — an unclosed fragment no viewer
    # will open, reported as a success, with neither the suite nor the battery
    # noticing. What is on disk is what gets checked.
    with tempfile.TemporaryDirectory() as d:
        primer = os.path.join(d, "ok-primer.json")
        json.dump(base, open(primer, "w", encoding="utf-8"))
        dest = os.path.join(d, "truncated.svg")

        liar = os.path.join(d, "liar")
        os.makedirs(os.path.join(liar, "scripts"))
        open(os.path.join(liar, "scripts", "fireworks.py"), "w", encoding="utf-8").write(
            "import sys\nopen(sys.argv[-1], 'w').write('<svg><g>')\nsys.exit(0)\n")
        run = subprocess.run([sys.executable, cli, "graph", primer, dest],
                             capture_output=True, text=True, cwd=d,
                             env=dict(os.environ, RIFTBOUND_FIREWORKS=liar))
        check("a truncated render is not announced as a diagram",
              run.returncode != 0 and not os.path.exists(dest)
              and "wrote " + dest not in run.stdout,
              f"rc={run.returncode}, exists={os.path.exists(dest)}")

        # `run.stdout or run.stderr` picks stdout whenever it is truthy, and
        # whitespace is truthy — the real traceback went in the bin.
        mute = os.path.join(d, "mute")
        os.makedirs(os.path.join(mute, "scripts"))
        open(os.path.join(mute, "scripts", "fireworks.py"), "w", encoding="utf-8").write(
            "import sys\nprint('   \\n  ')\n"
            "print('RealError: style unsupported', file=sys.stderr)\nsys.exit(1)\n")
        run = subprocess.run([sys.executable, cli, "graph", primer,
                              os.path.join(d, "m.svg")],
                             capture_output=True, text=True, cwd=d,
                             env=dict(os.environ, RIFTBOUND_FIREWORKS=mute))
        check("the renderer's own complaint reaches the user",
              "RealError: style unsupported" in (run.stderr or ""),
              (run.stderr or "").strip()[-80:] or "nothing on stderr")

        # An override the caller SET is a statement. Falling through to the
        # default search meant one typo rendered from a different install and
        # said nothing about it.
        run = subprocess.run([sys.executable, cli, "graph", primer,
                              os.path.join(d, "t.svg")],
                             capture_output=True, text=True, cwd=d,
                             env=dict(os.environ,
                                      RIFTBOUND_FIREWORKS=os.path.join(d, "typo-here")))
        check("a mis-set override is refused rather than quietly ignored",
              run.returncode != 0 and "RIFTBOUND_FIREWORKS" in (run.stderr or run.stdout),
              f"rc={run.returncode}")

    # Fireworks lives outside the skill folder and ADR 0004 forbids depending on
    # anything out there. A missing install must cost a picture, never the IR.
    with tempfile.TemporaryDirectory() as d:
        good = os.path.join(d, "ok-primer.json")
        json.dump(base, open(good, "w", encoding="utf-8"))
        env = dict(os.environ)
        env.pop("RIFTBOUND_FIREWORKS", None)   # an unset override, not a broken one
        env["HOME"] = d                        # so the default search paths miss too
        run = subprocess.run([sys.executable, cli, "graph", good, os.path.join(d, "x.svg")],
                             capture_output=True, text=True, cwd=d, env=env)
        ir_file = os.path.join(d, "x.fireworks.json")
        check("with no Fireworks install the IR is still written, and says how to render it",
              os.path.exists(ir_file) and "render architecture" in run.stdout,
              f"rc={run.returncode}")
        # Exit 0 here would say the caller got `x.svg`. They did not.
        check("and naming an SVG that could not be produced is not reported as success",
              run.returncode != 0 and not os.path.exists(os.path.join(d, "x.svg"))
              and "x.svg" in run.stdout,
              f"rc={run.returncode}; the message must name the file it did not write")
        # Whereas a destination WE chose is a soft degradation, not a failure:
        # the export ran, and the IR is the artifact this project stands behind.
        run2 = subprocess.run([sys.executable, cli, "graph", good],
                              capture_output=True, text=True, cwd=d, env=env)
        check("but a defaulted destination degrades quietly and exits 0",
              run2.returncode == 0, f"rc={run2.returncode}")
        check("and that IR is complete on its own",
              os.path.exists(ir_file) and all(
                  k in json.load(open(ir_file, encoding="utf-8"))
                  for k in ("schema_version", "mode", "nodes", "arrows")))


def cli_output_paths():
    """Where a report actually lands when the caller names a relative path.

    `rules_cli.main()` chdirs into the skill folder so the tools can find their
    data. Input paths were already resolved before that — a relative input
    otherwise found a shipped sample of the same name and printed "6/6
    verified" for an answer nobody wrote. The mirror image went unnoticed:
    every relative OUTPUT path was silently relocated INTO the skill folder,
    and the CLI reported success naming a file that is not where it said.
    """
    print("\n=== cli: output goes where the caller asked ===")
    import tempfile

    cli = os.path.join(HERE, "rules_cli.py")
    primer = os.path.join(HERE, "hot-fepr-primer.json")
    ruling = os.path.join(HERE, "heron-answer.json")

    with tempfile.TemporaryDirectory() as d:
        # `--format=mermaid` explicitly. `graph` defaults to Fireworks now, so
        # this silently started requiring an optional EXTERNAL tool — the suite
        # failed outright on any machine without it, in a skill whose whole
        # premise is that copying the folder is enough (ADR 0004). It also
        # asserted the wrong thing where the tool WAS present, writing an SVG
        # into a file called graph.mmd. What is under test here is where a
        # relative path lands, and mermaid needs nothing to test that.
        r = subprocess.run([sys.executable, cli, "graph", primer, "graph.mmd",
                            "--format=mermaid"],
                           capture_output=True, text=True, cwd=d)
        landed = os.path.exists(os.path.join(d, "graph.mmd"))
        check("a relative output path lands where the caller ran the command",
              landed and r.returncode == 0,
              f"in lib instead: {os.path.exists(os.path.join(HERE, 'graph.mmd'))}")
        # And the CLI must name the path it actually wrote, not the one asked for.
        #
        # `.split()[-1]` on an empty stdout raised IndexError and took the whole
        # suite down with it — so an unrelated mutant that made `graph` exit
        # non-zero was reported as "<suite crashed>" instead of by the checks
        # that had already failed by name a hundred lines above. A check that
        # crashes on the failure it is watching for is worse than no check.
        reported = (r.stdout.strip().split() or [""])[-1]
        check("and the CLI reports the path it actually wrote",
              bool(reported) and os.path.realpath(reported)
              == os.path.realpath(os.path.join(d, "graph.mmd")),
              r.stdout.strip()[:80] or "no output")
        for stray in ("graph.mmd", "report.html"):
            if os.path.exists(os.path.join(HERE, stray)):
                os.remove(os.path.join(HERE, stray))

    with tempfile.TemporaryDirectory() as d:
        # `out = args[1]` bound --force as the destination. The renderer then
        # dropped it from its own positionals and wrote report.html into the
        # skill folder — the flag worked, the file went somewhere else, and the
        # caller was told nothing.
        # NO explicit destination. With one supplied the flag sits at args[2]
        # and the defect never fires — the first version of this check passed
        # against the broken code it was named for, which is the failure mode
        # this whole file exists to refuse.
        r = subprocess.run([sys.executable, cli, "render", ruling, "--force"],
                           capture_output=True, text=True, cwd=d)
        check("--force is not bound as the render destination",
              os.path.exists(os.path.join(d, "report.html"))
              and not os.path.exists(os.path.join(HERE, "report.html")),
              f"rc={r.returncode}; {(r.stderr or '')[:60]}")
        check("and no file is named after the flag",
              not os.path.exists(os.path.join(d, "--force"))
              and not os.path.exists(os.path.join(HERE, "--force")))
        for stray in ("out.html", "report.html", "--force"):
            if os.path.exists(os.path.join(HERE, stray)):
                os.remove(os.path.join(HERE, stray))


def python_floor():
    """The skill must import on the oldest Python it might meet.

    Packaged for Claude Desktop / mobile it runs in a sandbox whose interpreter
    we do not choose, and stock macOS still ships 3.9. A single `bool | None`
    in a dataclass field is evaluated at class creation, so one annotation took
    the entire skill down with a TypeError before anything ran.
    """
    print("\n=== python floor (3.9) ===")
    import ast
    offenders = []
    for path in sorted(glob.glob(os.path.join(HERE, "*.py"))):
        tree = ast.parse(open(path, encoding="utf-8").read())
        for node in ast.walk(tree):
            ann = getattr(node, "annotation", None) or getattr(node, "returns", None)
            if isinstance(ann, ast.BinOp) and isinstance(ann.op, ast.BitOr):
                offenders.append(f"{os.path.basename(path)}:{node.lineno}")
    check("no PEP-604 unions in annotations (3.10+ only)", not offenders,
          ", ".join(offenders[:4]))


def render_gate():
    """The one thing between a failed verification and a pretty report.

    `cmd_render` shells straight into render_report.py without calling
    verify_answer, so main()'s gate is the whole safety property on that path —
    and it was exercised by nobody. Deleting those five lines was a green-suite
    change that would ship a green badge over a fabricated citation.
    """
    print("\n=== render gate (end-to-end) ===")
    import tempfile
    base = json.load(open(os.path.join(HERE, "demo-answer.json"), encoding="utf-8"))
    base["notes"][0]["cites"] = [{"rule": "CR:999.9.z", "quote": "invented"}]

    with tempfile.TemporaryDirectory() as d:
        src = os.path.join(d, "ghost.json")
        out = os.path.join(d, "out.html")
        json.dump(base, open(src, "w", encoding="utf-8"))

        r = subprocess.run([sys.executable, os.path.join(HERE, "render_report.py"), src, out],
                           capture_output=True, text=True, cwd=HERE)
        check("a fabricated citation exits non-zero", r.returncode != 0, f"rc={r.returncode}")
        check("and writes no report at all", not os.path.exists(out))

        r = subprocess.run([sys.executable, os.path.join(HERE, "render_report.py"), src, out,
                            "--force"], capture_output=True, text=True, cwd=HERE)
        forced = os.path.exists(out) and open(out, encoding="utf-8").read()
        check("--force renders but marks the citation failed",
              bool(forced) and 'class="stamp bad"' in forced)
        check("--force still forces the verdict to UNSETTLED",
              bool(forced) and 'class="forced"' in forced
              and re.search(r'class="disp[^"]*"[^>]*>\s*UNSETTLED', forced) is not None,
              "the word UNSETTLED appears on every page; the banner does not")


def attribution_and_spans(idx):
    """Two blocker regressions that would both fail SILENTLY, looking correct."""
    print("\n=== document attribution + holding spans ===")
    import copy
    from render_report import verify_answer, render, note_number

    base = json.load(open(os.path.join(HERE, "demo-answer.json"), encoding="utf-8"))

    # 790 ids exist only in TR. A bare id was stamped "CR", so Tournament Rules
    # text reached the reader labelled Core Rules with a green verified badge.
    a = copy.deepcopy(base)
    a["notes"][0]["cites"] = [{
        "rule": "104.1",
        "quote": "vs. Core Rules: In some cases, information in this document may contradict",
    }]
    r = verify_answer(a, idx)
    cite = r["notes"][0]["cites"][0]
    check("a TR-only bare id is labelled TR, not CR", cite["cite_as"].startswith("TR:"),
          cite["cite_as"])
    check("a missing document prefix is reported, so the report will not render",
          any("104.1" in p and "TR" in p for p in r["_problems"]),
          "; ".join(r["_problems"])[:70] or "no problem raised")

    # A monotonic cursor dropped any span listed before an earlier one, which
    # silently stripped viktor's crux from the holding line.
    a = copy.deepcopy(base)
    line = a["holding"]["line"]
    spans = a["holding"].get("spans", [])
    if len(spans) >= 2:
        reordered = sorted(spans, key=lambda s: -line.find(s["text"]))
        a["holding"]["spans"] = reordered
        html = render(verify_answer(a, idx), idx)
        check("every span renders even when listed out of document order",
              html.count('class="noteref"') >= len(spans),
              f'{html.count(chr(34) + "noteref" + chr(34))} refs for {len(spans)} spans')
        for sp in spans:
            if sp["text"] not in html:
                check(f'span "{sp["text"][:22]}" survives reordering', False)
                break
        else:
            check("no span text is lost when reordered", True)

    # Overlapping spans cannot both be placed, so one used to disappear from
    # the rendered line while verification reported no problem at all.
    a = copy.deepcopy(base)
    line = a["holding"]["line"]
    if a["holding"].get("spans"):
        outer = a["holding"]["spans"][0]["text"]
        # A slice from the middle of an existing span is genuinely nested and
        # unique in the line, unlike a bare word that may recur earlier.
        inner = outer[6:len(outer) - 6]
        if len(inner) > 8 and line.count(inner) == 1:
            a["holding"]["spans"] = a["holding"]["spans"] + [
                {"text": inner, "basis": "inferred", "note": a["notes"][0]["id"]}]
            r = verify_answer(a, idx)
            check("overlapping holding spans fail verification",
                  any("overlaps" in p for p in r["_problems"]),
                  "; ".join(r["_problems"])[:70] or "no problem raised")
            # and the invariant behind it: what verifies clean must fully render
            clean = verify_answer(copy.deepcopy(base), idx)
            n = len(clean["holding"]["spans"])
            check("a clean answer renders every one of its spans",
                  render(clean, idx).count('class="noteref"') >= n, f"{n} spans")

    # The shipped samples are the fixtures most likely to regress unnoticed.
    for sample in ("viktor-answer.json", "heron-answer.json"):
        path = os.path.join(HERE, sample)
        if not os.path.exists(path):
            continue
        ans = verify_answer(json.load(open(path, encoding="utf-8")), idx)
        html = render(ans, idx)
        n = len(ans["holding"].get("spans", []))
        check(f"{sample}: all {n} holding spans render",
              html.count('class="noteref"') >= n,
              f'{html.count(chr(34) + "noteref" + chr(34))} refs')


def topic_blocks(idx):
    """A cross-reference must never look like "the rules say nothing".

    "see rule 467. Scoring" lands on a bare heading whose rules are SIBLINGS
    (468-472), not children. An agent that reads the empty subtree as silence
    reaches the worst wrong answer this system can produce.
    """
    print("\n=== topic blocks (heading -> sibling rules) ===")
    scoring = idx.get("467", "CR")
    check("467 Scoring is recognised as a bare heading", bool(scoring) and idx.is_topic_heading(scoring))
    block = idx.topic_block(scoring) if scoring else []
    ids = [r["id"] for r in block]
    check("its block resolves to the sibling rules", ids == ["468", "469", "470", "471", "472"],
          ", ".join(ids) or "empty")

    # The block must stop at the next heading, not run to the end of the doc.
    check("the block stops at the next heading", len(ids) < 12, f"{len(ids)} sections")

    # An ordinary section with children must be left completely alone.
    flow = idx.get("829", "CR")
    check("a section with children is not treated as a heading",
          bool(flow) and not idx.is_topic_heading(flow))
    check("a section with children has no topic block", idx.topic_block(flow) == [])

    # A one-line rule that merely lacks children is not a heading either.
    body = next((r for r in idx.rules.values()
                 if r["doc"] == "CR" and r.get("depth") == 1
                 and r["text"].strip().endswith(".")
                 and not any(x.get("parent") == r["id"] and x["doc"] == "CR"
                             for x in idx.rules.values())), None)
    check("a childless one-line RULE is not treated as a heading",
          body is not None and not idx.is_topic_heading(body),
          f'{body["id"] if body else "?"}')

    # Chapter headings hold sub-headings, not rules. 316.7.e and 348.1 both
    # say "see rule 463", and two tournament rules say "see 600" — so these
    # are reachable cross-reference targets, not hypotheticals.
    combat = idx.get("463", "CR")
    contents = idx.topic_contents(combat) if combat else []
    check("a chapter heading lists its sub-headings",
          [r["id"] for r in contents] == ["464", "465", "466", "467"],
          ", ".join(r["id"] for r in contents) or "empty")
    # Skipping body sections to reach more sub-headings was tried; it let 463
    # run past its four steps into Layers and Modes of Play.
    check("a chapter listing does not run past its own topic",
          all(r["id"] < "473" for r in contents), ", ".join(r["id"] for r in contents))

    # TR:600 ran past its own formats into chapter 700 before this was bounded.
    formats = idx.get("600", "TR")
    fc = [r["id"] for r in (idx.topic_contents(formats) if formats else [])]
    check("a contents listing stops at the next chapter",
          fc == ["601", "602", "603", "604"], ", ".join(fc) or "empty")

    # The invariant that matters: no heading is a dead end.
    dead = [f'{d}:{r["id"]}' for d in ("CR", "TR")
            for r in idx._top_sections(d)
            if idx.is_topic_heading(r)
            and not idx.topic_block(r) and not idx.topic_contents(r)]
    check("no heading resolves to nothing at all", not dead, ", ".join(dead[:4]))


def symbols_and_notes():
    """The legend is derived from the rules, so it must survive a renumber."""
    print("\n=== symbol legend + note references ===")
    import json as _json
    from corpus import rules_json
    from symbols import build_legend, scan
    from render_report import note_number, verify_answer, render
    from verify_citations import RuleIndex

    rules = _json.load(open(rules_json(), encoding="utf-8"))
    legend = build_legend(rules)

    # Six domains (CR 134.2.a-f) plus exhaust/might/any/own/keyword (CR 135.2.e).
    check("all six domain shorthands are derived", 
          all(t in legend for t in "RGBOPY"),
          "missing " + ", ".join(t for t in "RGBOPY" if t not in legend))
    check("the non-domain symbols are derived",
          all(t in legend for t in ("A", "C", "E", "M", ">")),
          ", ".join(sorted(legend)))
    check("every legend entry cites a real rule",
          all(e["rule"] in {r["id"] for r in rules if r["doc"] == "CR"}
              for e in legend.values()))

    # Bracketed prose must not be glossed as symbols or the key becomes noise.
    check("prose brackets are not treated as symbols",
          not scan("issue a [Warning], then [do X] on [Reaction]", legend))
    check("real symbols are found", scan("[E]: Add [Y].", legend) == {"E", "Y"})

    # [>] is written into the page as `[&gt;]`; scanning raw HTML missed it.
    from render_report import legend_html
    esc_page = "<p>a keyword marker [&gt;] and a cost of [E]</p>"
    lg = legend_html(esc_page, RuleIndex())
    check("an HTML-escaped symbol still reaches the legend", "[&gt;]" in lg or "[>]" in lg,
          "keyword marker missing from the key")

    check("note ids reduce to numbers", note_number("n12") == "12")
    check("an unnumbered note id survives", note_number("intro") == "intro")

    src = os.path.join(HERE, "demo-answer.json")
    if os.path.exists(src):
        idx = RuleIndex()
        html = render(verify_answer(json.load(open(src, encoding="utf-8")), idx), idx)
        check("the legend placeholder is always substituted", "<!--LEGEND-->" not in html)
        spans = json.load(open(src, encoding="utf-8"))["holding"].get("spans", [])
        if spans:
            check("holding spans carry a superscript note ref",
                  html.count('class="noteref"') >= len(spans),
                  f'{html.count(chr(34) + "noteref" + chr(34))} refs for {len(spans)} spans')


def metric_consistency(idx):
    """Three defects that each rendered a completely normal-looking report.

    None crashed, none changed any fixture's bytes, and the suite was green
    through all three. That is precisely why they are pinned here: the render
    gate catches a fabricated citation, but nothing was watching the numbers
    and notices the reader actually reads.
    """
    print("\n=== headline metrics + card notices ===")
    import tempfile
    from render_report import all_cites, card_notice, verify_answer

    # 1. The console tally and the report headline are the same quantity and
    #    must never be computed twice. They were, and had drifted: the
    #    counterargument's citations are verified like any other, but only the
    #    headline counted them, so the terminal said 6/6 where the report it had
    #    just written said 8/8.
    src = os.path.join(HERE, "flow-counter-answer.json")
    ans = verify_answer(json.load(open(src, encoding="utf-8")), idx)
    every = len(all_cites(ans))
    notes_only = sum(len(n.get("cites", [])) for n in ans["notes"])
    check("the fixture reaches the counterargument path at all", every > notes_only,
          f"{every} cites total vs {notes_only} in notes")

    with tempfile.TemporaryDirectory() as d:
        out = os.path.join(d, "fc.html")
        r = subprocess.run([sys.executable, os.path.join(HERE, "render_report.py"), src, out],
                           capture_output=True, text=True, cwd=HERE)
        m = re.search(r"citations\s*:\s*(\d+)/(\d+)", r.stdout)
        check("the console reports a citation tally", bool(m), r.stdout.strip()[:80])
        if m:
            check("and it counts every citation the verifier checked",
                  int(m.group(2)) == every, f"console {m.group(2)}, actual {every}")
        html = open(out, encoding="utf-8").read()
        i = html.find("citations verified verbatim")
        near = " ".join(re.sub(r"<[^>]+>", " ", html[max(0, i - 200):i]).split())
        check("the headline agrees with the console", f"{every}/{every}" in near, near[-40:])

    # 2. Errata and incomplete-text are independent; a card can carry both.
    both = card_notice({"errata": "the 2026-07-16 update", "incomplete": "granted effect"})
    check("a card that is both erratum'd AND short shows both notices",
          "card-errata" in both and "card-gap" in both, both[:60])
    check("a card with neither shows no notice", card_notice({}) == "")

    # 3. An answer that ABSTAINS is not an answer that failed verification. The
    #    no-notes path set _forced unconditionally, so an author's honest
    #    UNSETTLED rendered the banner "forced to UNSETTLED (was UNSETTLED)".
    def _empty(disp):
        return verify_answer({"notes": [], "holding": {"disposition": disp, "line": "x",
                                                       "spans": []}}, idx)["holding"]
    check("an already-UNSETTLED answer with no notes is not marked forced",
          _empty("UNSETTLED").get("_forced") is None)
    check("but a YES with no notes still is",
          _empty("YES").get("_forced") == "YES")


def rendered_surfaces(idx):
    """The surfaces this rebuild actually changed, over ALL five fixtures.

    The harness used to open demo, viktor and heron only — and demo has no
    cards and produces no symbol legend, so the two surfaces the rebuild
    touched most were reached by fixtures nothing loaded. The check that the
    legend placeholder is always substituted passed on demo because the legend
    was empty and the marker was replaced with the empty string. It had never
    looked at a rendered legend row.
    """
    print("\n=== rendered surfaces (all five fixtures) ===")
    import copy
    import tempfile
    from render_report import BASIS, _CSS, _JS, clip, legend_html, render, verify_answer

    # A legend row is a citation like any other. Every report on main carried a
    # fabricated "[1] / [2] = that much Energy" row citing CR 429.5, harvested
    # out of the overlay JS's own `m[1]`/`m[2]`. Ninety-eight checks stayed
    # green through it, because nothing compared the legend to the visible page.
    # Counted across the loop below: if the row regex ever stops matching, the
    # per-fixture check would pass on an empty list and prove nothing. Three of
    # the five fixtures do render a legend, so zero rows overall is a broken
    # check rather than a clean report.
    seen_rows = [0]

    check("script bodies do not reach the legend",
          legend_html(f"<p>no symbols here</p><script>{_JS}</script>", idx) == "")
    # A FIXED hostile stylesheet, not live _CSS: _CSS happens to contain no
    # bracket tokens, so this passed with <style> stripping removed altogether.
    _hostile = "@media print{.x{content:'[2]'}}.y::after{content:'[A]'}"
    check("style bodies do not reach the legend",
          legend_html(f"<style>{_hostile}</style><p>no symbols here</p>", idx) == "")

    for sample in ("demo", "viktor", "heron", "flow-counter", "vi-cost"):
        src = os.path.join(HERE, f"{sample}-answer.json")
        ans = verify_answer(json.load(open(src, encoding="utf-8")), idx)
        page = render(ans, idx)

        # Every legend entry must name a symbol the reader can actually see.
        # The legend's OWN rows have to come out of the haystack first: each row
        # prints the token it glosses, so comparing the page against itself made
        # every row its own witness and the check could not fail. That is exactly
        # the fabrication it was written to catch.
        body = re.sub(r"<(script|style)\b.*?</\1>", " ", page, flags=re.S | re.I)
        body = re.sub(r'<div class="sym-row">.*?</div>', " ", body, flags=re.S)
        visible = __import__("html").unescape(re.sub(r"<[^>]+>", " ", body))
        glossed = [__import__("html").unescape(t) for t in
                   re.findall(r'class="sym"[^>]*>\[([^\]]+)\]</code>', page)]
        missing = [t for t in glossed if f"[{t}]" not in visible]
        check(f"{sample}: every legend entry names a symbol on the page",
              not missing, f"{len(glossed)} rows, fabricated {missing}")
        seen_rows[0] += len(glossed)

        # The rail restates the verdict in its own markup. A desync renders
        # perfectly and contradicts the plate beside it. An open question has no
        # verdict word, so the rail restates the LINE — the token must never
        # reach a reader's eye.
        _disp = ans["holding"]["disposition"]
        rd = re.search(r'class="rail-disp[^"]*">\s*([^<]+)', page)
        _said = rd.group(1).strip() if rd else ""
        if _disp == "ANSWER":
            ok = bool(_said) and "ANSWER" not in _said and _said.split("…")[0][:24] in ans["holding"]["line"]
        else:
            ok = _said == _disp
        check(f"{sample}: the rail restates the verified verdict", ok,
              f'rail said {_said[:40]!r} for {_disp}')

        ids = set(re.findall(r'\sid="([^"]+)"', page))
        dead = sorted(h for h in set(re.findall(r'href="#([^"]+)"', page)) if h not in ids)
        check(f"{sample}: every in-page link resolves", not dead, ", ".join(dead[:4]))

        # The copy-cite string is what a judge pastes into a dispute. It used to
        # hardcode 2026-07-16 while the masthead read corpus.CR, so the next
        # rules update would have made every button assert a version the report
        # itself did not claim.
        stale = sorted(d for d in set(re.findall(r"\d{4}-\d{2}-\d{2}", page))
                       if d not in ans["corpus"].values())
        check(f"{sample}: no citation asserts a rules date the corpus disclaims",
              not stale, f'{stale} not in {sorted(set(ans["corpus"].values()))}')

    # Every fixture's corpus CR is 2026-07-16 — exactly the literal the copy-cite
    # string used to hardcode — so a whole-report check agrees with the bug and
    # cannot see it. Exercised at cite_html directly, because the corpus stamp
    # is now cross-checked against the index and a bogus date is (correctly)
    # rejected before rendering.
    from render_report import cite_html
    base = json.load(open(os.path.join(HERE, "demo-answer.json"), encoding="utf-8"))
    vans = verify_answer(copy.deepcopy(base), idx)
    a_cite = vans["notes"][0]["cites"][0]
    frag = cite_html(a_cite, idx, {"CR": "2099-01-02", "TR": "2088-03-04"})
    # Distinct per document: with both set to the same date, a cite_html that
    # ignored `doc` and always read corpus["CR"] passed. A TR cite must carry
    # TR's date.
    _want = "2099-01-02" if a_cite["cite_as"].startswith("CR") else "2088-03-04"
    drifted = sorted(d for d in set(re.findall(r"\d{4}-\d{2}-\d{2}", frag)) if d != _want)
    check("citation dates follow the corpus, not a hardcoded literal",
          not drifted, f"{drifted} survived a corpus move")

    # And a corpus with no entry for the citation's document must say so rather
    # than reach for whatever value happens to be first in the dict — `generated`
    # sits in the same block, so that fallback asserted the report's build date
    # as the rules version.
    partial = cite_html(a_cite, idx, {"generated": "2026-08-12"})
    check("a missing corpus entry reads as unstated, not as another date",
          "version unstated" in partial and "2026-08-12" not in partial,
          partial[partial.find("data-cite"):][:90])

    check("the legend row check actually inspected rows", seen_rows[0] > 0,
          f"{seen_rows[0]} legend rows seen across the five fixtures")

    # The key decodes the marks on the verdict line, but derived itself from the
    # NOTES. `_check_holding` constrains only grounded spans, so an inferred span
    # over a grounded note is valid input — and printed a dotted mark on the one
    # line everyone reads with no row explaining it. No fixture hits this, which
    # is why it stayed latent; construct it.
    mark = copy.deepcopy(json.load(open(os.path.join(HERE, "vi-cost-answer.json"),
                                        encoding="utf-8")))
    mark["holding"]["spans"][0]["basis"] = "inferred"
    marked = render(verify_answer(mark, idx), idx)
    # Match the emitted ROW, not the bare token — `k-structural` also appears in
    # the stylesheet, so a looser probe passes on any page ever rendered.
    has_row = 'class="key-item k-structural"' in marked
    check("the key explains every mark the verdict line uses",
          'class="sp-inferred"' not in marked or has_row,
          "inferred span rendered with no structural row in the key")

    # Two spans with the SAME text, on a line where it occurs once, passed every
    # guard: the overlap test exempts identical ranges as harmless, and the
    # placement cursor then dropped one to unmarked prose with zero problems.
    dup = copy.deepcopy(json.load(open(os.path.join(HERE, "flow-counter-answer.json"),
                                       encoding="utf-8")))
    dup["holding"]["spans"].append({"text": dup["holding"]["spans"][0]["text"],
                                    "basis": dup["holding"]["spans"][0]["basis"],
                                    "note": dup["notes"][1]["id"]})
    rdup = verify_answer(dup, idx)
    check("a span the renderer would drop fails verification",
          any("cannot be placed" in p for p in rdup["_problems"]), str(rdup["_problems"])[:70])

    # A `gap` span means "the rules are silent"; it used to be drawn with the
    # dotted-blue mark that means "it follows from the rules below" — RANK 1
    # rendered as RANK 2, on the one line everyone reads.
    gp = copy.deepcopy(json.load(open(os.path.join(HERE, "vi-cost-answer.json"),
                                      encoding="utf-8")))
    gp["holding"]["spans"][1]["basis"] = "gap"
    gpage = render(verify_answer(gp, idx), idx)
    check("a gap span is not drawn as a structural one",
          'class="sp-gap"' in gpage and 'class="sp-inferred"' not in gpage)

    # Every basis the schema accepts must have a paint. `inferred` did not, so a
    # note the key printed as Structural rendered in the muted treatment a gap
    # note gets — the key and the note disagreeing about the same claim.
    unpainted = [k for k in BASIS if f".b-{k} " not in _CSS]
    check("every accepted note basis has a stylesheet rule", not unpainted,
          f"unpainted: {unpainted}")

    # The basis coercion must run before ANYTHING reads note["basis"].
    nob = copy.deepcopy(base)
    del nob["notes"][0]["basis"]
    try:
        check("a note missing its basis is reported, not crashed",
              any("basis" in p for p in verify_answer(nob, idx)["_problems"]))
    except KeyError as e:
        check("a note missing its basis is reported, not crashed", False, f"KeyError {e}")

    # A failure to LOAD the card data used to render "not found — no card by
    # this name" on every card: a factual assertion about the corpus, produced
    # by a tooling failure, with zero problems and the verdict untouched. This
    # is the exact conversion SKILL.md forbids the model from making.
    import card_bridge
    _real = card_bridge.CardBridge
    try:
        class _Boom:
            def __init__(self, *a, **k):
                raise RuntimeError("card data unreadable")
        card_bridge.CardBridge = _Boom
        broke = render(verify_answer(copy.deepcopy(json.load(
            open(os.path.join(HERE, "vi-cost-answer.json"), encoding="utf-8"))), idx), idx)
    finally:
        card_bridge.CardBridge = _real
    # The REALISTIC failure is an EMPTY index, not an exception: corpus.load_cards
    # swallows OSError/ValueError and returns {}, so a deleted or corrupt
    # cards.json builds a CardBridge that simply knows no cards. The guard added
    # last round only caught the exception arm, so it passed on a tree with no
    # cards.json at all — certifying a property the code did not have.
    class _Empty:
        cards = {}
    try:
        card_bridge.CardBridge = _Empty
        emptied = render(verify_answer(copy.deepcopy(json.load(
            open(os.path.join(HERE, "vi-cost-answer.json"), encoding="utf-8"))), idx), idx)
    finally:
        card_bridge.CardBridge = _real
    check("an EMPTY card index is not reported as a missing card",
          "no card by this name" not in emptied and "did not load" in emptied,
          "an empty index is a data failure, not 1037 simultaneous typos")

    check("unreadable card data is not reported as a missing card",
          "no card by this name" not in broke, "rendered the card as nonexistent")
    check("and says the database failed instead",
          "did not load" in broke)

    # A cite with no quote stamps ✗ UNVERIFIED, but the note stayed "verified"
    # and the verdict was never downgraded — the two halves of the page
    # disagreeing. Omitting the quote is the cheapest way to defeat the
    # verbatim gate; it must not also buy a clean verdict.
    noq = copy.deepcopy(base)
    noq["notes"][0]["cites"] = [{"rule": noq["notes"][0]["cites"][0]["rule"]}]
    rq = verify_answer(noq, idx)
    check("a quote-less citation downgrades its note",
          rq["notes"][0]["verified"] is False)
    check("and forces the verdict", rq["holding"]["disposition"] == "UNSETTLED")

    # "Considered and rejected" reads as evidence of thoroughness, so an id
    # invented there buys more credibility than one in a note. It was never
    # verified at all.
    rej = copy.deepcopy(base)
    rej["considered_rejected"] = [{"rule": "CR:999.9.z", "why": "invented"}]
    check("a fabricated considered_rejected id fails verification",
          any("999.9.z" in p for p in verify_answer(rej, idx)["_problems"]))

    # The masthead's provenance came from the answer file with nothing to check
    # it against, while every rule in the index carries its own version.
    stamp = copy.deepcopy(base)
    stamp["corpus"] = dict(stamp["corpus"], CR="2027-01-01")
    check("a corpus stamp contradicting the index fails verification",
          any("2027-01-01" in p for p in verify_answer(stamp, idx)["_problems"]))

    # card_terms carries `ambiguous` and rules_cli shouts about it; the renderer
    # dropped it, so one printing rendered as though it were the card.
    amb = copy.deepcopy(json.load(open(os.path.join(HERE, "vi-cost-answer.json"),
                                       encoding="utf-8")))
    amb["cards"] = ["Ahri"]
    check("an ambiguous card name says so on the page",
          "This name matches" in render(verify_answer(amb, idx), idx))

    # render_report already refused to truncate on a mid-render crash; the
    # RULEBOOK still did, and ensure_rulebook tested only os.path.exists — so a
    # 0-byte rules.html was accepted forever and every citation link opened an
    # empty page while the report still stamped them verified.
    #
    # Pointed at a temp path, NOT the real rulebook: running this against a
    # truncating build would otherwise destroy the committed artifact, which is
    # exactly what happened once while developing the fix.
    import corpus as _corpus
    import render_rulebook as _rbmod
    _real_path = _corpus.rulebook_html_path
    _real_render = _rbmod.render_rulebook
    with tempfile.TemporaryDirectory() as d:
        decoy = os.path.join(d, "rules.html")
        open(decoy, "w", encoding="utf-8").write("PREVIOUS GOOD RULEBOOK")
        try:
            _corpus.rulebook_html_path = lambda: decoy
            def _boom(*a, **k):
                raise KeyError("id")
            _rbmod.render_rulebook = _boom
            try:
                _rbmod.main()
            except Exception:
                pass
        finally:
            _corpus.rulebook_html_path = _real_path
            _rbmod.render_rulebook = _real_render
        check("a crash inside the rulebook render leaves the previous one intact",
              open(decoy, encoding="utf-8").read() == "PREVIOUS GOOD RULEBOOK")

    # data/rules.html is generated and committed, so it can silently fall behind
    # its generator — it had, by two CSS fixes, until this was written. Every
    # report links into this file, so a stale copy is a stale rulebook for every
    # reader of every report.
    with tempfile.TemporaryDirectory() as d:
        fresh = os.path.join(d, "rules.html")
        try:
            _corpus.rulebook_html_path = lambda: fresh
            _rbmod.main()
        finally:
            _corpus.rulebook_html_path = _real_path
        committed = open(_real_path(), encoding="utf-8").read()
        check("the committed rulebook matches what the generator produces",
              open(fresh, encoding="utf-8").read() == committed,
              "run `rules_cli.py rulebook` and commit the result")

    # ---- round 6 ----------------------------------------------------------
    from render_report import place_spans
    from verify_citations import RuleIndex, verify_citation

    # Every one of the corpus's 262 Examples was uncitable: subtree_text includes
    # them so the quote passed, then the narrowing pass searched only r["text"],
    # found nothing, and flipped it to "paraphrased". `rules_cli.py rule` PRINTS
    # those Examples, so the tool invited the quote it then rejected — and a
    # false rejection is direct pressure toward --force.
    _ex = [(r["doc"], r["id"], e) for r in idx.rules.values() for e in r.get("examples", [])]
    _bad = [x for x in _ex if not verify_citation(idx, x[1], x[2], None, x[0]).ok]
    check("the corpus actually carries Examples to test", len(_ex) > 200, f"{len(_ex)}")
    check("an official Example can be cited verbatim", _ex and not _bad,
          f"{len(_bad)} of {len(_ex)} rejected")

    # A whitespace-only quote normalises to "" and "" is a substring of
    # everything, so it verified. `checked` closed "omit the quote"; a single
    # space was cheaper and reopened it.
    for _blank in (" ", "\n", "\xa0"):
        check(f"a whitespace-only quote ({_blank!r}) is refused",
              not verify_citation(idx, "441.1.a", _blank, None, "CR").ok)

    # Narrowing tightens a VAGUE cite; it must not move an already-exact one.
    _keep = verify_citation(idx, "124", "changes zones to or from a Non-Board Zone", None, "CR")
    check("the cited rule keeps its own quote", _keep.cite_as == "124",
          f"rewritten to {_keep.cite_as}")

    # 143 sentences in the corpus have several equally deep homes; choosing one
    # by iteration order asserted a fact the corpus does not support.
    _amb = verify_citation(idx, "602",
                           "At low OPL, this can be allowed by the head judge.", None, "TR")
    check("an ambiguous quote home is reported, not guessed",
          any("appears in" in p for p in _amb.problems), str(_amb.problems)[:70])

    # Blocks are matched SEPARATELY, never joined. A quote welded from the end
    # of one block and the start of the next exists nowhere Riot published, and
    # matching a concatenation stamped it verified — the cheapest possible way
    # to defeat a verbatim gate.
    _sr = idx.get("811.1.d.2.a", "CR")
    _splice = (" ".join(_sr["text"].split()[-6:]) + " "
               + " ".join(_sr["examples"][0].split()[:6]))
    check("a quote spliced across a block boundary is refused",
          not verify_citation(idx, "811.1.d.2.a", _splice, None, "CR").ok)

    # Normative text outranks Examples when narrowing. Examples routinely
    # restate a NEIGHBOURING rule, so equal ranking attributed a quote to a rule
    # whose own text does not contain it — 383.3.a onto 383.3.a.3, the opposite
    # case, under a banner asserting the quote "lives" there.
    # Normative text must outrank an Example when both could host a quote.
    # Pinned on a SYNTHETIC index: no arrangement in the real corpus can tell
    # the two rankings apart once "the cited rule wins if it hosts the quote"
    # is in place, so a corpus-based check here passes with the ordering
    # reversed — the mutation battery proved exactly that. The property is a
    # design decision (Examples restate NEIGHBOURING rules, so they must never
    # outrank normative text), and it deserves a test that cannot drift with
    # the corpus.
    with tempfile.TemporaryDirectory() as d:
        synth = os.path.join(d, "rules.json")
        json.dump([
            {"doc": "CR", "id": "900", "text": "Parent with no quote.", "depth": 1,
             "parent": None, "section": "900", "section_title": "Synthetic",
             "version": "test", "examples": [], "see_also": []},
            {"doc": "CR", "id": "900.1", "text": "the disputed clause lives here",
             "depth": 2, "parent": "900", "section": "900",
             "section_title": "Synthetic", "version": "test",
             "examples": [], "see_also": []},
            {"doc": "CR", "id": "900.1.a", "text": "Deeper rule, different subject.",
             "depth": 3, "parent": "900.1", "section": "900",
             "section_title": "Synthetic", "version": "test",
             "examples": ["Example: the disputed clause lives here, restated."],
             "see_also": []},
        ], open(synth, "w", encoding="utf-8"))
        _sidx = RuleIndex(synth)
        _sres = verify_citation(_sidx, "900", "the disputed clause lives here", None, "CR")
        check("normative text outranks an Example when narrowing",
              _sres.cite_as == "900.1",
              f"narrowed to {_sres.cite_as}, not the rule whose own text holds the quote")

    # A descendant's Example must verify at every ancestor: it used to verify at
    # the child and be called "paraphrased" one level up.
    _anc = [rid for rid in ("811.1.d.2.a", "811.1.d.2", "811.1.d", "811.1", "811")
            if not verify_citation(idx, rid, _sr["examples"][0], None, "CR").ok]
    check("a descendant Example verifies at every ancestor", not _anc, f"failed at {_anc}")
    check("a fabricated quote is still rejected",
          not verify_citation(idx, "103.2.a.2", "I invented this entirely", None, "CR").ok)

    # The pairwise overlap guard compared FIRST occurrences while placement uses
    # a cursor, so it rejected spans the renderer places perfectly.
    _line = "Yes, so the cost is checked at that point, and the cost stands unchanged."
    _sp = [{"text": "so the cost is checked at that point", "basis": "grounded", "note": "n1"},
           {"text": "the cost", "basis": "grounded", "note": "n2"}]
    _ok = copy.deepcopy(base)
    _ok["holding"]["line"] = _line
    _ok["holding"]["spans"] = [dict(x, note=_ok["notes"][i]["id"]) for i, x in enumerate(_sp)]
    # Asserts NO problems at all, not "no problem containing the word overlap".
    # Keying on one word let a rejection worded differently sail through while
    # the answer was still refused.
    _okp = verify_answer(_ok, idx)["_problems"]
    check("spans the renderer places are not rejected at all",
          not place_spans(_line, _ok["holding"]["spans"])[1] and not _okp, str(_okp)[:90])

    # A note with NO citations was stamped "● grounded — a rule states this in
    # so many words". Omitting the cite entirely was cheaper than omitting the
    # quote, which was already refused.
    _nc = copy.deepcopy(base)
    _nc["notes"][1]["basis"] = "grounded"
    _nc["notes"][1]["cites"] = []
    _rnc = verify_answer(_nc, idx)
    check("a grounded note with no citations fails verification",
          any("cites none" in p for p in _rnc["_problems"]))
    check("and does not stay verified", _rnc["notes"][1]["verified"] is False)

    # ...but structural may synthesise from the rules its NEIGHBOURS cite, which
    # is what "it follows from the rules below" means. Requiring a cite here
    # would reject legitimate reasoning and push the author to --force.
    _st = copy.deepcopy(base)
    _st["notes"][1]["basis"] = "structural"
    _st["notes"][1]["cites"] = []
    check("a structural note may synthesise without citing",
          not any("cites none" in p for p in verify_answer(_st, idx)["_problems"]))

    # rules_checked is what licenses a claim that the rules are SILENT.
    _rc = copy.deepcopy(base)
    _rc["notes"][0]["rules_checked"] = ["999.9.z"]
    check("a fabricated rules_checked id fails verification",
          any("999.9.z" in p for p in verify_answer(_rc, idx)["_problems"]))

    # The weakest link must include gap notes — RANK scores gap lowest for
    # exactly this comparison, and the page claims "the lowest link".
    _g = copy.deepcopy(base)
    _g["notes"][-1]["basis"] = "gap"
    _g["notes"][-1]["rules_checked"] = ["441"]
    _g["notes"][-1]["cites"] = []
    check("a gap note is the weakest link", verify_answer(_g, idx)["_strength"] == "gap")

    # A span may not claim more support than the note it rests on.
    _up = copy.deepcopy(base)
    _up["notes"][-1]["basis"] = "gap"
    _up["notes"][-1]["rules_checked"] = ["441"]
    _up["notes"][-1]["cites"] = []
    for _s in _up["holding"]["spans"]:
        _s["note"] = _up["notes"][-1]["id"]
        _s["basis"] = "inferred"
    check("a span cannot claim more support than its note",
          any("claims inferred" in p for p in verify_answer(_up, idx)["_problems"]))

    # Duplicate note ids: every anchor resolves to the first match.
    _d = copy.deepcopy(base)
    _d["notes"][1]["id"] = _d["notes"][0]["id"]
    check("duplicate note ids fail verification",
          any("duplicate note id" in p for p in verify_answer(_d, idx)["_problems"]))

    # The narrowed notice must name the ORIGIN; it named the destination.
    _n = copy.deepcopy(base)
    for _c in _n["notes"][0]["cites"]:
        _c["rule"] = _c["rule"].split(":")[0] + ":" + _c["rule"].split(":")[1].split(".")[0]
    _rn = verify_answer(_n, idx)
    _narrowed = [c for nn in _rn["notes"] for c in nn.get("cites", []) if c.get("narrowed")]
    # Requires a narrowed citation to EXIST — all([]) is True, so this passed
    # when narrowing was disabled entirely and no notice was rendered at all.
    check("the narrowing case is actually exercised", bool(_narrowed), "nothing narrowed")
    check("a narrowed citation names where it came FROM",
          _narrowed and all(c["narrowed"] != c["cite_as"].split(":", 1)[1] for c in _narrowed),
          f"{[(c['narrowed'], c['cite_as']) for c in _narrowed][:2]}")

    # The rulebook must be in numeric id order — one pair was not, putting a set
    # legality date under the wrong set's heading in the committed artifact.
    _rules = json.load(open(_corpus.rules_json(), encoding="utf-8"))
    def _k(rid):
        return [(0, int(x), "") if x.isdigit() else (1, 0, x) for x in rid.split(".")]
    _oo = 0
    for _doc in ("CR", "TR"):
        _seq = [r["id"] for r in _rules if r["doc"] == _doc]
        _oo += sum(1 for a2, b2 in zip(_seq, _seq[1:]) if _k(a2) > _k(b2))
    # Reads the RENDERED page, not the source. Asserting that the identifier
    # "id_sort_key" appears in a file passes whether or not the sort is called
    # — and deleting the call left this green while the committed artifact put
    # Unleashed's legality date under the Vendetta heading.
    _emitted = re.findall(r'id="(CR|TR)-([^"]+)"', open(_real_path(), encoding="utf-8").read())
    _wrong = []
    for _doc in ("CR", "TR"):
        _ids = [i for d, i in _emitted if d == _doc]
        _wrong += [(a2, b2) for a2, b2 in zip(_ids, _ids[1:]) if _k(a2) > _k(b2)]
    check("the rendered rulebook is in numeric id order", not _wrong,
          f"out of order: {_wrong[:3]}")
    check("the ordering check saw a real rulebook", len(_emitted) > 3000, f"{len(_emitted)} ids")

    # `render --force` bound the flag as the output path.
    with tempfile.TemporaryDirectory() as d:
        bad = os.path.join(d, "bad.json")
        outp = os.path.join(d, "out.html")
        ghost = copy.deepcopy(base)
        ghost["notes"][0]["cites"] = [{"rule": "CR:999.9.z", "quote": "invented"}]
        json.dump(ghost, open(bad, "w", encoding="utf-8"))
        # The TWO-argument form is the one that broke: `render_report.py bad.json
        # --force` bound the flag as argv[2], so it wrote a file called "--force"
        # and left the previous all-green report.html untouched beside it. A
        # three-arg call cannot see the bug.
        stray = os.path.join(d, "--force")
        prior = os.path.join(d, "report.html")
        open(prior, "w", encoding="utf-8").write("STALE ALL-GREEN REPORT")
        subprocess.run([sys.executable, os.path.join(HERE, "render_report.py"), bad, "--force"],
                       capture_output=True, text=True, cwd=d)
        check("--force is not mistaken for the output path",
              not os.path.exists(stray), "wrote a file literally named --force")
        check("and the forced report replaces the stale one",
              open(prior, encoding="utf-8").read() != "STALE ALL-GREEN REPORT")

    # Round 6 stopped answer files overriding the vendored card record but added
    # no check, so the mutation battery found the fix entirely unguarded. This is
    # the worst reachable shape: Riot's genuine artwork beside an invented
    # ability, under an errata banner calling the fabrication the CORRECTED text.
    _ov = copy.deepcopy(json.load(open(os.path.join(HERE, "vi-cost-answer.json"),
                                       encoding="utf-8")))
    _ov["cards"] = [{"name": "Vi - Hotheaded", "text": "INVENTED ABILITY: draw 9 cards.",
                     "stats": {"energy": 99}, "rule_sections": "829"}]
    _ovp = render(verify_answer(_ov, idx), idx)
    check("an answer cannot override the vendored card text",
          "INVENTED ABILITY" not in _ovp)
    check("nor iterate a string field per character",
          not re.findall(r'rules\.html#CR-(\d)"', _ovp),
          "rule_sections rendered one link per character")

    check("a rail claim is shortened even with no early space",
          len(clip("x" * 100)) <= 60, repr(clip("x" * 100))[:24])
    check("a short claim is left alone", clip("abc") == "abc")

    # Print is invisible to every other gate: screen rendering, the selftest and
    # a human reviewer all miss it. Only a judge with a printer finds out — and
    # the failure this guards inverted the argument, printing the grounded half
    # of the verdict line at 2.23:1 and the inferred half at 16.75:1.
    import render_rulebook as _rb
    for name, css in (("report", _CSS), ("rulebook", _rb._CSS)):
        # Comments stripped: the block's own comment explains the light-canvas
        # remap by naming `color-scheme:light`, so the probe was satisfied by
        # the prose describing the rule rather than by the rule.
        blk = re.sub(r"/\*.*?\*/", " ", css[css.index("@media print"):], flags=re.S)
        check(f"the {name} print sheet declares a light canvas", "color-scheme:light" in blk)
        gone = [t for t in ("--gold-500", "--slate-300", "--mist-100") if f"{t}:" not in blk]
        check(f"the {name} print sheet remaps the raw palette tokens", not gone, ", ".join(gone))

        # ...and remaps them to something LEGIBLE ON WHITE. Presence of the
        # declaration was the whole test, so remapping gold-500 to the near-white
        # mist-100 passed at 1.15:1 — worse than the 2.23:1 that motivated the
        # remap in the first place.
        _hex = dict(re.findall(r"(--[a-z0-9-]+):\s*(#[0-9a-fA-F]{6})", css))

        def _lum(h):
            def _c(v):
                v /= 255.0
                return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
            r_, g_, b_ = (int(h[i:i + 2], 16) for i in (1, 3, 5))
            return 0.2126 * _c(r_) + 0.7152 * _c(g_) + 0.0722 * _c(b_)

        _dim = []
        for _tok in ("--gold-500", "--slate-300", "--mist-100"):
            _m = re.search(re.escape(_tok) + r":\s*var\((--[a-z0-9-]+)\)", blk)
            _target = _hex.get(_m.group(1)) if _m else None
            if not _target:
                continue
            _ratio = (1.05) / (_lum(_target) + 0.05)
            if _ratio < 4.5:
                _dim.append(f"{_tok}->{_m.group(1)} {_ratio:.2f}:1")
        check(f"the {name} print remap is legible on white", not _dim, "; ".join(_dim))

    weird = copy.deepcopy(base)
    weird["holding"]["spans"][0]["basis"] = "definitional"
    check("an unknown holding-span basis is reported, not silently coerced",
          any("basis" in p for p in verify_answer(weird, idx)["_problems"]))

    # A crash INSIDE render, with the previous report already on disk.
    #
    # `--force` is load-bearing here and was not always: this used to rely on
    # verify_answer ignoring `corpus`, so removing that key verified clean and
    # died in render. A later round made a missing corpus a verification
    # PROBLEM, which meant the subprocess exited at the gate and never reached
    # render at all — the check kept passing while proving nothing. That was
    # predicted as a consequence of adding the corpus check, and it happened.
    # --force skips the gate so the crash lands where this check aims it.
    with tempfile.TemporaryDirectory() as d:
        src, out = os.path.join(d, "crash.json"), os.path.join(d, "out.html")
        crash = copy.deepcopy(base)
        crash.pop("corpus")
        json.dump(crash, open(src, "w", encoding="utf-8"))
        open(out, "w", encoding="utf-8").write("PREVIOUS GOOD REPORT")
        r = subprocess.run(
            [sys.executable, os.path.join(HERE, "render_report.py"), src, out, "--force"],
            capture_output=True, text=True, cwd=HERE)
        check("the render-crash check actually reaches render",
              "corpus" in (r.stderr or "") or r.returncode != 0,
              "the gate refused first, so render never ran")
        check("a crash inside render leaves the previous report intact",
              r.returncode != 0 and open(out, encoding="utf-8").read() == "PREVIOUS GOOD REPORT",
              f"rc={r.returncode}")


def research_tools(idx):
    """The commands an agent NAVIGATES with, before it writes anything.

    These had zero coverage in either gate through eight review rounds, and that
    is exactly how their defects survived. A renderer bug produces a visibly odd
    report; a `grep` that hides the second half of a rule produces a CONFIDENT
    WRONG ANSWER that then cites correctly. Nothing downstream can catch that —
    the citation verifier checks that a quote is real, not that the reasoning
    resting on it is.
    """
    print("\n=== the tools an agent researches with ===")
    import tempfile

    from retrieve import BadQuery, Retriever
    # The FTS index is a build artifact and gitignored, so a fresh checkout — CI,
    # or anyone who has never run a search — has none. Every check below then
    # died on "Rule index missing", taking the suite with it. Building needs
    # only the committed data/rules.json, not the source markdown.
    from rules_cli import ensure_index
    ensure_index()
    r = Retriever(os.path.join(HERE, "rules.db"))

    # FTS5 reads - ' . and brackets as operators. Returning [] for a REJECTED
    # query made `grep` print "no matches", which is a claim about the RULES.
    # `Quick-Draw` is CR section 819; its output was byte-identical to a
    # nonsense word's.
    for term in ("Quick-Draw", "can't", "471.1.b"):
        try:
            hits = r.search(term, 5)
            check(f"grep finds {term!r}, which exists", bool(hits), "reported as absent")
        except BadQuery:
            check(f"grep finds {term!r}, which exists", False, "query rejected")
    try:
        check("a genuinely absent term still returns nothing",
              not r.search("zamboni", 5))
    except BadQuery:
        check("a genuinely absent term still returns nothing", False, "rejected instead")

    # Truncation is the quiet one: 142 rules carry a negation past 110 chars.
    out = subprocess.run(
        [sys.executable, os.path.join(HERE, "rules_cli.py"), "grep",
         '"activated ability" AND showdown', "-n", "2"],
        capture_output=True, text=True, cwd=HERE).stdout
    check("grep shows the clause that reverses a rule",
          "not during a Showdown" in out,
          "CR:145.2 rendered without its negation")
    check("grep does not clip the section title",
          "Units may have Activated Abilities" in out)

    import copy

    from render_report import render, verify_answer

    # The disposition is a CSS class as well as a label, and it was unvalidated —
    # a value with spaces became several bogus classes and silently disabled the
    # print sheet keyed on the same name.
    _dbase = json.load(open(os.path.join(HERE, "demo-answer.json"), encoding="utf-8"))
    _bad = copy.deepcopy(_dbase)
    _bad["holding"]["disposition"] = "IT DEPENDS ON THE ZONE"
    check("a disposition outside the vocabulary is refused",
          any("disposition" in p for p in verify_answer(_bad, idx)["_problems"]))

    # Most rules questions are not yes/no questions. Forcing one produced a
    # shipped example answering "How much energy does Vi cost?" with YES.
    _open = copy.deepcopy(json.load(open(os.path.join(HERE, "vi-cost-answer.json"),
                                         encoding="utf-8")))
    _open["holding"]["disposition"] = "ANSWER"
    _openp = render(verify_answer(_open, idx), idx)
    check("an open question prints no verdict word",
          'class="disp ' not in _openp and ">ANSWER<" not in _openp)
    check("and leads with the holding line instead", 'class="hline is-lead"' in _openp)

    # The forcing path must still bite. An open question whose citation fails is
    # UNSETTLED like any other — that is the whole gate, and a new disposition
    # must not route around it.
    _openbad = copy.deepcopy(_open)
    _openbad["notes"][0]["cites"] = [{"rule": "CR:999.9.z", "quote": "invented"}]
    _r = verify_answer(_openbad, idx)
    check("a failed citation still forces UNSETTLED from ANSWER",
          _r["holding"]["disposition"] == "UNSETTLED" and _r["holding"].get("_forced") == "ANSWER",
          f'{_r["holding"]["disposition"]} forced from {_r["holding"].get("_forced")}')

    # Riot writes illustrations two ways, and only the singular `Example:` was
    # recognised — so six rules absorbed a plural `Examples:` list into their
    # NORMATIVE text, where the verifier accepted a quote of an illustration as
    # a quote of the rule. The items are separate; joining them would fabricate
    # a sentence Riot never published.
    _swallowed = [r for r in idx.rules.values() if "Examples:" in r["text"] and r["doc"] == "CR"]
    check("no CR rule carries an Examples list as normative text", not _swallowed,
          f"{[r['id'] for r in _swallowed][:4]}")
    _listed = idx.get("124.1", "CR")
    check("a plural Examples list is split into separate items",
          len(_listed.get("examples", [])) >= 4, f"{_listed.get('examples')}")
    check("and each item stands alone, not welded to its neighbours",
          all(e.count(".") <= 2 for e in _listed.get("examples", [])),
          f"{_listed.get('examples')}")

    # An answer file that is not where the caller says it is must be REFUSED.
    # The guard here abspath'd the name only when the file EXISTED, so a missing
    # one stayed relative, chdir(HERE) resolved it against lib/, and one of the
    # five shipped samples was verified and delivered instead — "8/8 verified
    # verbatim", exit 0, for a question nobody asked.
    with tempfile.TemporaryDirectory() as d:
        _sub = subprocess.run(
            [sys.executable, os.path.join(HERE, "rules_cli.py"), "verify", "heron-answer.json"],
            capture_output=True, text=True, cwd=d)
        check("a missing answer file is refused, not substituted",
              _sub.returncode != 0 and "verified" not in _sub.stdout,
              f"rc={_sub.returncode} {_sub.stdout.strip()[:60]}")

    # A crash DURING THE WRITE, not during render. The check further up forces a
    # failure inside render(); this one lets render succeed and fails the swap,
    # which is the case an in-place write destroys. Same invariant: a failure
    # never leaves a stale artifact looking current.
    #
    # Drives render_report.main() itself rather than re-implementing the write
    # here — a hand-rolled sequence would test this file, not the code.
    import render_report as _rrw
    with tempfile.TemporaryDirectory() as _d:
        _keep = os.path.join(_d, "ruling.html")
        open(_keep, "w", encoding="utf-8").write("PREVIOUS RULING")
        _src = os.path.join(_d, "a.json")
        json.dump(json.load(open(os.path.join(HERE, "demo-answer.json"), encoding="utf-8")),
                  open(_src, "w", encoding="utf-8"))
        _real_replace, _real_argv = os.replace, sys.argv
        try:
            os.replace = lambda *a, **k: (_ for _ in ()).throw(OSError("disk full"))
            sys.argv = ["render_report.py", _src, _keep]
            try:
                _rrw.main()
            except BaseException:
                pass
        finally:
            os.replace, sys.argv = _real_replace, _real_argv
        check("a failed write leaves the previous ruling intact",
              open(_keep, encoding="utf-8").read() == "PREVIOUS RULING",
              "the saved ruling was destroyed by a failed rewrite")
        check("and leaves no half-written temp file behind",
              not os.path.exists(_keep + ".tmp"))

    # A query FTS5 rejects gets rewritten. The rewrite can mean something else
    # entirely — `combat -damage` became the phrase "combat damage", returning
    # the complement of the request — so the rewrite must be disclosed.
    rw = subprocess.run(
        [sys.executable, os.path.join(HERE, "rules_cli.py"), "grep", "combat -damage"],
        capture_output=True, text=True, cwd=HERE).stdout
    check("a rewritten query says so", "searched" in rw and "not the one you typed" in rw,
          rw.strip()[:80])

    # Disclosure alone is not enough — WHICH rewrite matters. A phrase form
    # means something narrower than the words typed, so a punctuated multi-word
    # query must still find the rule containing all of them.
    _qd = subprocess.run(
        [sys.executable, os.path.join(HERE, "rules_cli.py"), "grep", "Quick-Draw equipment"],
        capture_output=True, text=True, cwd=HERE).stdout
    check("a punctuated multi-word query finds the rule holding both words",
          "CR:150.3" in _qd, _qd.strip()[:80])

    # The corpus version must be READ from each document, not stamped from one
    # literal — two documents deriving from a single constant can never disagree,
    # which made the per-document provenance check vacuous by construction.
    from parse_rules import source_version
    with tempfile.TemporaryDirectory() as _d:
        _f = os.path.join(_d, "doc.md")
        open(_f, "w", encoding="utf-8").write("# T\n\nLast Updated: 2099-12-31\n\n100. x\n")
        check("the corpus stamp is read from the document, not hardcoded",
              source_version(_f) == "2099-12-31", source_version(_f))
        _g = os.path.join(_d, "us.md")
        open(_g, "w", encoding="utf-8").write("# T\n\nLast Updated 7/16/2026\n\n100. x\n")
        check("a US-format date normalises to ISO", source_version(_g) == "2026-07-16",
              source_version(_g))

    # 37 topic headings are cross-reference targets, and SKILL.md sends the
    # agent to `rule <id>` after a `see also`. One word with no pointer is
    # indistinguishable from "the rules are silent".
    for _rid, _want in (("467", "sections 468-472"), ("463", "chapter heading")):
        _o = subprocess.run(
            [sys.executable, os.path.join(HERE, "rules_cli.py"), "rule", _rid],
            capture_output=True, text=True, cwd=HERE).stdout
        check(f"rule {_rid} points at where its content lives", _want in _o, _o.strip()[-70:])

    # Two tools that disagree about rule order is worse than either being wrong:
    # CR:323's own text says "in the order described".
    kids = subprocess.run(
        [sys.executable, os.path.join(HERE, "rules_cli.py"), "rule", "323"],
        capture_output=True, text=True, cwd=HERE).stdout
    seq = re.findall(r"^\s+(323\.\d+)\.", kids, re.M)
    check("rule lists children in numeric order", seq == sorted(seq, key=_num_key), str(seq[:6]))
    check("the child-order check saw children", len(seq) > 5, f"{len(seq)}")

    # The retriever's own children() had the same lexicographic bug in SQL.
    rows = [x["rid"] for x in r.children("CR:465.2.c")]
    check("the retriever orders children numerically",
          rows == sorted(rows, key=_num_key), str(rows[:5]))


def _num_key(rule_id):
    return [(0, int(x), "") if x.isdigit() else (1, 0, x) for x in rule_id.split(".")]


def main():
    print("rules-report selftest")
    parser_fidelity()
    idx = corpus_integrity()
    verifier_regression(idx)
    holding_invariants(idx)
    rulebook_and_links()
    card_rendering()
    symbols_and_notes()
    topic_blocks(idx)
    attribution_and_spans(idx)
    render_gate()
    research_tools(idx)
    metric_consistency(idx)
    rendered_surfaces(idx)
    primer_invariants(idx)
    export_and_history(idx)
    shipped_primers(idx)
    fireworks_export(idx)
    committed_diagrams(idx)
    cli_output_paths()
    python_floor()

    print()
    if FAILS:
        print(f"FAILED {len(FAILS)} of {RAN[0]}: {', '.join(FAILS)}")
        sys.exit(1)
    # The count is printed rather than documented. Hardcoding it in the README
    # meant it silently drifted every time a check was added.
    print(f"all {RAN[0]} checks passed — safe to answer against this corpus")

    # ...and immediately, the number that qualifies it.
    #
    # "All N checks passed" sounds like coverage and is not. It is coverage of
    # the behaviours somebody thought to attack: a check with no mutant behind
    # it has never been observed to fail, and is therefore indistinguishable
    # from one that CANNOT. Worse, adding such a check raises N, so the
    # headline improves while the evidence behind it does not.
    #
    # Printed here rather than left to `mutants`, because this is the line
    # people quote. The honest claim is a pair.
    print(_proof_summary())


def _proof_summary():
    """How many checks the battery has actually WATCHED fail. Never blocks a run.

    Read from `proven-checks.json`, which `mutants` writes with the names it saw
    go red. The first version of this derived the number by matching each
    mutant's `expect` against check names — that counts CLAIMS, and a claim can
    be false: ten of mine were, for a group that never ran inside the battery.
    It under-counts too, since one mutant usually reddens several checks and
    `expect` names one. Wrong in both directions from one technique, which is
    how you tell it was measuring something else.

    Intersected with the checks that exist NOW, so a renamed check drops its old
    credit rather than carrying a proof nobody has repeated.
    """
    try:
        import json as _json, re as _re
        names = set(_re.findall(r'check\(\s*"([^"]{6,})"', open(__file__).read()))
        path = os.path.join(HERE, "proven-checks.json")
        if not os.path.exists(path):
            return (f"  {len(names)} distinct checks. How many have been OBSERVED "
                    f"to fail is unknown here — no record yet; run `mutants` to "
                    f"write one. Unknown is not zero, and it is not fine either.")
        with open(path, encoding="utf-8") as fh:
            recorded = set(_json.load(fh))
        proven = names & recorded
        forgotten = len(recorded - names)
        note_ = (f", {forgotten} recorded name(s) no longer exist and were dropped"
                 if forgotten else "")
        return (f"  of {len(names)} distinct checks, {len(proven)} have been "
                f"watched to fail ({len(proven) * 100 // max(len(names), 1)}%)"
                f"{note_}. The rest hold today and have never been tested against "
                f"a defect — run `mutants` to move that number.")
    except Exception as exc:
        return f"  (could not read which checks are proven: {exc})"
    sys.exit(0)


if __name__ == "__main__":
    main()
