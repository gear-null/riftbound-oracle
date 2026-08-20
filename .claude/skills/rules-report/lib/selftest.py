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
        # perfectly and contradicts the plate beside it.
        rd = re.search(r'class="rail-disp">([^<]+)<', page)
        check(f"{sample}: the rail restates the verified verdict",
              bool(rd) and rd.group(1) == ans["holding"]["disposition"],
              f'rail {rd and rd.group(1)} vs {ans["holding"]["disposition"]}')

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
    python_floor()

    print()
    if FAILS:
        print(f"FAILED {len(FAILS)} of {RAN[0]}: {', '.join(FAILS)}")
        sys.exit(1)
    # The count is printed rather than documented. Hardcoding it in the README
    # meant it silently drifted every time a check was added.
    print(f"all {RAN[0]} checks passed — safe to answer against this corpus")
    sys.exit(0)


if __name__ == "__main__":
    main()
