#!/usr/bin/env python3
"""`rules` — deterministic tools for answering Riftbound rules questions.

Architecture note. This deliberately does NOT do semantic retrieval over the
rules. That was built, measured at recall@10 of 32%, and rejected. The reason
is structural: users ask in CARD vocabulary and the rules are written in RULES
vocabulary, and card names essentially never appear in rule text — so no amount
of BM25 tuning bridges the gap.

Instead the agent NAVIGATES. These commands are the primitives it navigates
with — each one exact, deterministic, and free of model judgement:

    rules card <name>       exact card lookup -> printed text + keywords + rule links
    rules rule <id>...      exact rule + ancestor spine + children + cross-refs
    rules grep <pattern>    lexical search over rule text (agent-driven, not RAG)
    rules section <id>      a whole numbered section, in document order
    rules report <json>     verify + render + open — the ONLY way to finish an answer
    rules graph <primer>    a primer's step graph as Mermaid, derived from its exits
    rules verify <json>     mechanical citation gate (report runs this for you)
    rules rulebook          (re)generate the anchored HTML rulebook
    rules selftest          regression harness; run after every rules update
    rules mutants           proves the selftest can fail — run before a release
    rules render <json>     interactive HTML report

The division of labour: the agent decides WHAT to look at, code decides whether
the citations it produced are real.
"""
import json, os, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from corpus import rules_json as _rules_json
RULES_JSON = _rules_json()
RULES_DB = os.path.join(HERE, "rules.db")
REPORTS = os.path.normpath(os.path.join(HERE, "..", "reports"))


def _idx():
    from verify_citations import RuleIndex
    return RuleIndex(RULES_JSON)


def cmd_rule(args):
    """Print rules with the ancestry that makes them mean anything."""
    idx = _idx()
    for spec in args:
        doc, rid = (spec.split(":", 1) if ":" in spec else ("CR", spec))
        r = idx.get(rid, doc)
        if not r:
            print(f"{doc}:{rid}  NOT FOUND at this corpus version")
            continue
        print(f"=== {doc}:{rid}  [{r['section']}. {r['section_title']}]  @{r['version']} ===")
        for a in idx.ancestry(rid, doc):
            mark = ">>" if a["id"] == rid else "  "
            print(f"{mark} {'  ' * (a['depth'] - 1)}{a['id']}. {a['text']}")
        kids = [x for x in idx.rules.values()
                if x["doc"] == doc and x["parent"] == rid]
        for k in sorted(kids, key=lambda x: _idkey(x["id"])):
            print(f"   {'  ' * (k['depth'] - 1)}{k['id']}. {k['text']}")
        # A topic heading owns no children, so everything above prints one word
        # and stops. SKILL.md sends the agent here after following a `see also`,
        # and 37 headings are cross-reference targets — an empty result is
        # indistinguishable from "the rules are silent", which this codebase
        # calls the most dangerous wrong conclusion it can reach. `cmd_section`
        # already resolves these; `cmd_rule` simply never asked.
        if not kids and idx.is_topic_heading(r):
            block = idx.topic_block(r)
            if block:
                print(f"\n   -- {rid} is a heading; its rules are sections "
                      f"{block[0]['id']}-{block[-1]['id']}. `section {doc}:{rid}` --")
            else:
                contents = idx.topic_contents(r)
                if contents:
                    print(f"\n   -- {rid} is a chapter heading; it continues with "
                          f"{', '.join(c['id'] for c in contents[:6])}"
                          f"{' …' if len(contents) > 6 else ''}. `section {doc}:{rid}` --")
        for ex in r.get("examples", []):
            print(f"   Example: {ex}")
        if r.get("see_also"):
            print(f"   see also: {', '.join(r['see_also'])}")
        print()


def _idkey(rule_id):
    return [(0, int(s), "") if s.isdigit() else (1, 0, s) for s in rule_id.split(".")]


def cmd_section(args):
    """A whole numbered section, in document order.

    Some topics are written as a bare heading whose rules are SIBLING sections
    ("467. Scoring", then 468-472), so asking for the heading alone returns one
    word. Where that happens the following block is printed too — otherwise a
    cross-reference like "see rule 467. Scoring" looks like a dead end, and an
    empty result reads as "the rules are silent on this".
    """
    idx = _idx()
    doc, sec = (args[0].split(":", 1) if ":" in args[0] else ("CR", args[0]))
    rows = [r for r in idx.rules.values() if r["doc"] == doc and r["section"] == sec]
    if not rows:
        print(f"no section {doc}:{sec}")
        return

    def show(r):
        print(f"{'  ' * (r['depth'] - 1)}{r['id']}. {r['text']}")

    ordered = sorted(rows, key=lambda r: _idkey(r["id"]))
    for r in ordered:
        show(r)

    head = ordered[0]
    block = idx.topic_block(head)
    if block:
        print(f"\n  -- {head['id']} is a heading; its rules are sections "
              f"{block[0]['id']}-{block[-1]['id']} --\n")
        for r in block:
            show(r)
            kids = sorted(
                (x for x in idx.rules.values()
                 if x["doc"] == doc and x["id"].startswith(r["id"] + ".")),
                key=lambda x: _idkey(x["id"]),
            )
            for k in kids:
                show(k)
        return

    # A chapter heading holds sub-headings rather than rules. List them, so a
    # cross-reference like "see rule 463" leads somewhere instead of nowhere.
    contents = idx.topic_contents(head)
    if contents:
        print(f"\n  -- {head['id']} is a chapter heading; it continues with --\n")
        for r in contents:
            print(f"     {r['id']}. {r['text']}")
        print("\n  -- document order, not strict containment; "
              "`section <id>` any of the above --")


def cmd_grep(args):
    """Lexical search the agent drives itself. Not a retrieval pipeline.

    Capped, and now says so. A silent cap invites reading "12 hits" as "all
    the hits", and from there concluding the rules are silent on whatever fell
    below the cut — the one wrong answer this system most needs to avoid.
    """
    import textwrap

    from retrieve import BadQuery, Retriever
    ensure_index()
    limit = 12
    if "-n" in args:
        i = args.index("-n"); limit = int(args[i + 1]); args = args[:i] + args[i + 2:]
    r = Retriever(RULES_DB)
    query = " ".join(args)
    # One more than asked for, purely to detect truncation.
    try:
        hits, ran = r.search_disclosed(query, limit + 1)
    except BadQuery as e:
        # NEVER the no-matches sentence here. That sentence is a claim about the
        # RULES; this is a fact about the query, and printing the former for the
        # latter told the agent the rules were silent on terms that exist.
        print(f"  the search engine rejected that query: {e}")
        print("  FTS5 reads - ' . : and brackets as operators. Try the bare words,")
        print('  a quoted phrase ("quick draw"), or navigate by section number.')
        return
    # Text is NOT clipped. It was cut at 110 chars with no marker, and 142 rules
    # carry a "not"/"unless"/"except" AFTER that point — CR:145.2 displayed as
    # "...during the controlling player's Main Phase during a" when the rule ends
    # "and not during a Showdown." The agent read the reverse of the rule and
    # then cited it correctly, which no downstream check can catch. Titles were
    # clipped to 22 chars too, collapsing Priority (312) and Focus (313) into
    # the same visible label.
    if ran != query:
        # Never silent. A rewritten query can return the COMPLEMENT of what was
        # asked, and an agent reading confident hits has no way to know its
        # operators were dropped.
        print(f'  -- "{query}" is not valid FTS5 syntax; searched {ran} instead.')
        print("  -- these hits answer the rewritten query, not the one you typed. --")
    for h in hits[:limit]:
        print(f"{h['uid']:18} [{h['section']}. {h['section_title']}]")
        for line in textwrap.wrap(h["text"], width=96) or [""]:
            print(f"    {line}")
    if not hits and ran == query:
        print("  no matches — try another term, or navigate by section number")
    elif not hits:
        # The no-matches sentence is a claim about the RULES. It must never be
        # printed for a query that never ran as typed.
        print(f"  the rewritten query {ran} also found nothing — this is not "
              "evidence that the rules are silent")
    elif len(hits) > limit:
        print(f"\n  -- showing {limit}; more matches exist. `-n {limit * 4}` for more. --")
        print("  -- ranked by lexical overlap: good for locating, never proof of absence. --")


def format_stats(stats):
    """A readable one-liner from the structured stats.

    These used to travel as markdown ("**Energy:** 4 | ...") and print with the
    asterisks intact, because nothing downstream renders markdown.
    """
    if not stats:
        return ""
    bits = []
    for key, label in (("energy", "Energy"), ("might", "Might"), ("power", "Power")):
        if stats.get(key) is not None:
            bits.append(f"{stats[key]} {label}")
    for key in ("type", "rarity"):
        if stats.get(key):
            bits.append(str(stats[key]))
    if stats.get("domain"):
        bits.append("/".join(stats["domain"]))
    return " · ".join(bits)


def cmd_card(args):
    """Exact card lookup — the direction where vocabulary matching actually works."""
    from card_bridge import CardBridge
    b = CardBridge(RULES_JSON)
    name = " ".join(args)
    # Single-word names must resolve too — this previously fell straight
    # through to the "did you mean" path for an exact match like "Windsinger".
    plan = b.plan(name)
    hits = plan["cards"] if plan and plan["cards"] else []
    if not hits and name.lower() in b.cards:
        hits = [b.card_terms(b.cards[name.lower()])]
    if not hits:
        key = name.lower()
        near = [k for k in b.cards if key in k or k in key][:8]
        if not near:
            print(f"no card matching '{name}'")
            print("  (try fewer words — cards are matched on their base name)")
            return
        print(f"no exact match; did you mean: {', '.join(b.cards[k]['name'] for k in near)}")
        return
    for c in hits:
        # A bare name shared by different cards is the same hazard as a
        # near-miss: answering about one arbitrary printing is worse than
        # asking which was meant.
        if c.get("ambiguous"):
            print(f"!!! '{name}' MATCHES {len(c['ambiguous'])} DIFFERENT CARDS.")
            for full in c["ambiguous"]:
                print(f"      {full}")
            print("    Ask again with the full name. Showing the first only:")
        if c.get("inexact"):
            print(f"!!! NO CARD NAMED '{c['asked_as']}' EXISTS.")
            print(f"    Closest name match is '{c['name']}', which is a DIFFERENT card.")
            print(f"    Do not reason about '{c['asked_as']}' from this text.")
        print(f"=== {c['name']} ===")
        line = format_stats(c.get("stats"))
        if line:
            print(f"  {line}")
        print(f"  {c['text']}")
        if c.get("incomplete"):
            print(f"  !!! PRINTED TEXT INCOMPLETE — {c['incomplete']}.")
            print(f"      Do not conclude the card lacks an ability you cannot see here.")
        print(f"  keywords : {', '.join(c['keywords']) or '(none printed)'}")
        print(f"  -> rules : {', '.join(c['rule_sections']) or '(no keyword maps to a rule section)'}")
        print()


def ensure_index():
    """Build the FTS index if absent, from the vendored rules.json.

    rules.db is a build artifact and gitignored, so it never travels with a
    copied skill — which left `grep`, one of the six documented tools, dead on
    every fresh install. Worse, the traceback pointed at `build`, which needs
    the source markdown a copied skill does not have.

    The index derives entirely from data/rules.json, so it can be rebuilt
    offline with nothing else present.
    """
    if os.path.exists(RULES_DB):
        return
    print("  building the search index (first run)...")
    subprocess.run([sys.executable, os.path.join(HERE, "retrieve.py"), "build"],
                   check=True, cwd=HERE)


def cmd_rulebook(args):
    """(Re)generate the anchored HTML rulebook that reports link into."""
    from render_rulebook import main as build_rulebook
    build_rulebook()


def ensure_rulebook():
    """Build the rulebook if it is missing, so a citation link is never dead.

    Reports link to `../data/rules.html#CR-471.1.b.1`. If that file does not
    exist the links resolve to nothing and the report looks broken through no
    fault of the answer, so the first report generates it rather than leaving
    the user to discover the gap by clicking.
    """
    from corpus import rulebook_html_path
    # Size, not existence. A crash mid-render used to leave a 0-byte rules.html
    # behind, and an existence test happily accepted it forever — so every
    # citation link opened an empty page while the report still stamped them
    # verified. The floor is deliberately crude: any real rulebook is ~MBs, and
    # anything under a kilobyte is a failed write, not a small corpus.
    path = rulebook_html_path()
    if not os.path.exists(path) or os.path.getsize(path) < 1024:
        print("  building the rulebook reports link into (first run)...")
        cmd_rulebook([])


# `kind` decides which document an answer file is, and it is the ONE place that
# decision is made. Absent means "ruling": every answer written before primers
# existed omits the field, and those files must keep verifying and rendering
# byte-for-byte as they did — a format migration that silently reinterprets old
# artifacts is how a saved ruling comes back changed.
#
# An unknown value is refused rather than defaulted. Defaulting would route a
# typo'd "primmer" down the ruling path, where every primer-shaped key is simply
# unread — producing a confident report about a document nobody wrote.
KINDS = ("ruling", "primer")


def _kind(ans, src):
    kind = ans.get("kind", "ruling")
    if kind not in KINDS:
        raise SystemExit(
            f"{src}: kind {kind!r} is not one of {', '.join(KINDS)}.\n"
            "  Omit `kind` for a ruling; set it to \"primer\" for an explainer.")
    return kind


def _verify_for(kind):
    """(verify, all_cites, renderer module path) for a document kind."""
    if kind == "primer":
        from render_primer import all_cites, verify_primer
        return verify_primer, all_cites, os.path.join(HERE, "render_primer.py")
    from render_report import all_cites, verify_answer
    return verify_answer, all_cites, os.path.join(HERE, "render_report.py")


def cmd_report(args):
    """Verify, render and open — one step, so an answer cannot be half-delivered.

    Splitting this into `verify` then `render` meant an answer could be left as
    a JSON file plus an instruction to run something. The user should never be
    handed homework; finishing an answer means producing the report.
    """
    src = args[0]
    explicit = args[1] if len(args) > 1 and not args[1].startswith("-") else None
    # Both naming conventions collapse to the topic: heron-answer.json and
    # hot-fepr-primer.json become heron.html and hot-fepr.html, so the
    # reports folder reads as a list of subjects rather than of filenames.
    slug = os.path.splitext(os.path.basename(src))[0]
    slug = slug.replace("-answer", "").replace("-primer", "") or slug
    out = explicit or os.path.join(REPORTS, f"{slug}.html")
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)

    # Verify first; a failing gate must not silently produce a pretty report.
    raw = json.load(open(src, encoding="utf-8"))
    verify, _all_cites, renderer = _verify_for(_kind(raw, src))
    ans = verify(raw, _idx())
    if ans["_problems"]:
        print("VERIFICATION FAILED — not rendering:")
        for pb in ans["_problems"]:
            print(f"  ! {pb}")
        sys.exit(1)

    ensure_rulebook()
    subprocess.run([sys.executable, renderer, src, out], check=True)
    print(f"\nreport: {os.path.normpath(os.path.abspath(out))}")
    if "--no-open" not in args:
        # Sandboxed runners (Claude Desktop / mobile skills) have no browser and
        # no opener binary. Report what actually happened rather than claiming a
        # window opened somewhere the reader cannot see.
        opener = {"darwin": "open", "win32": "start"}.get(sys.platform, "xdg-open")
        opened = False
        try:
            rc = subprocess.run([opener, out], check=False,
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            opened = rc.returncode == 0
        except Exception:
            opened = False
        print("opened in your browser" if opened
              else "no browser here — open the file above, or download it from this session")


def cmd_verify(args):
    """The citation gate alone. Exit 1 if anything failed."""
    raw = json.load(open(args[0], encoding="utf-8"))
    kind = _kind(raw, args[0])
    verify, all_cites, _renderer = _verify_for(kind)
    ans = verify(raw, _idx())
    cites = all_cites(ans)
    nc = len(cites)
    nv = sum(1 for c in cites if c["verified"])
    if kind == "primer":
        print(f"topic       : {ans.get('topic', '')}")
        print(f"steps       : {len(ans.get('steps', []))}")
    else:
        print(f"disposition : {ans['holding']['disposition']}"
              + (f"  (FORCED from {ans['holding']['_forced']})"
                 if ans["holding"].get("_forced") else ""))
    print(f"citations   : {nv}/{nc} verified verbatim")
    label = "weakest step" if kind == "primer" else "weakest link"
    print(f"{label}: {ans['_weakest']} ({ans['_strength']})")
    # Narrowing is worth surfacing on both paths: it means the id written was
    # vaguer than the rule that actually says the thing.
    for src_item in _cite_sources(ans, kind):
        for c in src_item.get("cites", []) or []:
            if c.get("narrowed"):
                print(f"  narrowed: {src_item.get('id', '?')} {c['rule']} -> {c['cite_as']}")
    for p in ans["_problems"]:
        print(f"  ! {p}")
    sys.exit(1 if ans["_problems"] else 0)


def _cite_sources(ans, kind):
    """The id-bearing blocks whose citations `verify` annotated."""
    if kind == "primer":
        for step in ans.get("steps", []):
            yield step
            for ex in step.get("exits", []) or []:
                yield dict(ex, id=f"{step.get('id', '?')}→{ex.get('goto') or 'end'}")
    else:
        for note in ans.get("notes", []):
            yield note


def cmd_render(args):
    src = args[0]
    out = args[1] if len(args) > 1 else "report.html"
    _v, _c, renderer = _verify_for(_kind(json.load(open(src, encoding="utf-8")), src))
    ensure_rulebook()
    # Flags are forwarded, not dropped: --force is the documented escape hatch
    # and it lives in the renderer, so swallowing it here made the flag a no-op
    # on the one path a caller reaches for it.
    subprocess.run([sys.executable, renderer, src, out]
                   + [a for a in args if a.startswith("--")], check=True)


def cmd_graph(args):
    """Emit a primer's step graph as Mermaid source.

    Derived from the same verified transitions the report draws, so a diagram
    produced from this cannot assert an edge the citations do not. That is the
    point of having it: the website and any restyling pass work from the graph,
    not from a fresh reading of the prose.
    """
    src = args[0]
    raw = json.load(open(src, encoding="utf-8"))
    if _kind(raw, src) != "primer":
        raise SystemExit(f"{src}: `graph` needs a primer — a ruling has no step graph.")
    # Verified first. Emitting the graph from an unchecked file would hand the
    # website a diagram this project never stood behind.
    from render_primer import verify_primer
    ans = verify_primer(raw, _idx())
    if ans["_problems"]:
        print("VERIFICATION FAILED — not emitting a graph:", file=sys.stderr)
        for pb in ans["_problems"]:
            print(f"  ! {pb}", file=sys.stderr)
        sys.exit(1)
    import flowgraph
    text = flowgraph.mermaid(ans["steps"], ans.get("topic", "Procedure"))
    if len(args) > 1 and not args[1].startswith("-"):
        with open(args[1], "w", encoding="utf-8") as fh:
            fh.write(text)
        print(f"wrote {args[1]}")
    else:
        print(text, end="")


def cmd_mutants(args):
    """Reintroduce each defect the selftest claims to catch, and watch it fail.

    Seven review rounds found the same thing twice: checks that could not fail.
    A green suite is only evidence if its checks have been observed to go red,
    so this is the check on the checks. Slower than selftest — it runs the whole
    suite once per mutant — so it is a pre-release gate, not an inner loop.
    """
    sys.exit(subprocess.run([sys.executable, os.path.join(HERE, "mutants.py")],
                            cwd=HERE).returncode)


def cmd_selftest(args):
    """Regression harness — run after every rules update."""
    # selftest's contract IS its exit code; discarding it reported a
    # post-update regression as success to anything checking $?.
    sys.exit(subprocess.run([sys.executable, os.path.join(HERE, "selftest.py")], cwd=HERE).returncode)


def cmd_build(args):
    """Re-parse the source markdown into rules.json, then rebuild everything
    derived from it.

    The rulebook is rebuilt here on purpose: report citations link to
    `rules.html#CR-<id>`, and a rules update renumbers ids. Leaving the old
    HTML in place pointed every link at an anchor that had moved or vanished —
    silently, since a missing fragment just lands at the top of the page.
    """
    subprocess.run([sys.executable, os.path.join(HERE, "parse_rules.py"),
                    "--json", RULES_JSON], check=True, cwd=HERE)
    subprocess.run([sys.executable, os.path.join(HERE, "retrieve.py"), "build"],
                   check=True, cwd=HERE)
    cmd_rulebook([])


COMMANDS = {"rule": cmd_rule, "section": cmd_section, "grep": cmd_grep,
            "card": cmd_card, "verify": cmd_verify, "render": cmd_render,
            "build": cmd_build, "selftest": cmd_selftest, "report": cmd_report,
            "mutants": cmd_mutants, "graph": cmd_graph,
            "rulebook": cmd_rulebook}


def main():
    if len(sys.argv) < 2 or sys.argv[1] not in COMMANDS:
        print(__doc__)
        sys.exit(0 if len(sys.argv) < 2 else 2)

    # Resolve file arguments against the caller's cwd BEFORE chdir. Without
    # this, `report heron-answer.json` run from a project root silently opened
    # lib/heron-answer.json — a shipped sample — and printed "6/6 verified"
    # for an answer the user never wrote. Silent substitution is the same
    # failure this codebase refuses for near-miss card names.
    args = []
    for a in sys.argv[2:]:
        if not a.endswith(".json"):
            args.append(a)
            continue
        full = os.path.abspath(a)
        if not os.path.exists(full):
            # Refuse, rather than let chdir(HERE) find a same-named sample.
            sys.exit(f"no such answer file: {a}")
        args.append(full)

    os.chdir(HERE)
    COMMANDS[sys.argv[1]](args)


if __name__ == "__main__":
    main()
