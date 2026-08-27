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
import json, os, re, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

# The directory the user actually ran the command from. `main()` chdirs into
# HERE so the tools can find their data, which silently relocated every RELATIVE
# OUTPUT path into the skill folder: `graph primer.json out.mmd` printed "wrote
# out.mmd" and put it in lib/. Input paths were already resolved before the
# chdir for the mirror-image reason — a relative input found a shipped sample of
# the same name. Captured at import, because by the time a command runs the cwd
# is gone.
CWD = os.getcwd()

from corpus import rules_json as _rules_json
RULES_JSON = _rules_json()
RULES_DB = os.path.join(HERE, "rules.db")
REPORTS = os.path.normpath(os.path.join(HERE, "..", "reports"))

# The history page lives WITH the reports, not above them, so a user who copies
# the folder keeps the index that describes it.
INDEX_NAME = "index.html"

# Diagrams are not reports, and they were landing in the same folder — so
# `reports/` held `combat.svg` and `ok.fireworks.json` beside the answers, and
# the history had to filter them out by extension. Give them their own place
# instead of teaching every reader of that folder which files to ignore.
DIAGRAMS = os.path.join(REPORTS, "diagrams")

REPORT_INDEX_HTML = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Riftbound Oracle — answered</title><style>
:root{--ink-900:#060b14;--ink-700:#0f1e33;--ink-500:#1e3a52;--mist:#e4f1f5;
 --slate:#7a96a8;--gold-700:#785a28;--gold-500:#c8aa6e;
 --display:"Beaufort for LOL",Cinzel,Georgia,serif;
 --body:"TT Norms Pro Compact",Barlow,system-ui,-apple-system,"Segoe UI",Arial,sans-serif}
*{box-sizing:border-box}
body{margin:0;background:var(--ink-900);color:var(--mist);
 font:400 16px/1.6 var(--body);padding:2.5rem 1.25rem}
main{max-width:60rem;margin:0 auto}
h1{font:500 1.6rem/1.3 var(--display);color:var(--gold-500);margin:0 0 .2rem;
 letter-spacing:.01em}
p.sub{color:var(--slate);margin:0 0 1.8rem;font-size:.93rem}
table{width:100%;border-collapse:collapse;font-size:.92rem}
th{text-align:left;font-weight:600;color:var(--slate);font-size:.72rem;
 text-transform:uppercase;letter-spacing:.09em;padding:.5rem .6rem;
 border-bottom:1px solid var(--gold-700)}
td{padding:.62rem .6rem;border-bottom:1px solid var(--ink-500);vertical-align:top}
td.w{color:var(--slate);white-space:nowrap;font-size:.84rem}
td.k{color:var(--slate);font-size:.84rem}
td.d{font-size:.76rem;letter-spacing:.06em;color:var(--gold-500)}
a{color:var(--mist);text-decoration:none;border-bottom:1px solid var(--gold-700)}
a:hover{border-bottom-color:var(--gold-500);color:#fff}
footer{margin-top:2rem;color:var(--slate);font-size:.8rem;line-height:1.5}
@media (max-width:34rem){td.k,th.k{display:none}}
</style></head><body><main>
<h1>Answered</h1>
<p class="sub">{{COUNT}} report(s) in this folder, newest first. A
<b>portable</b> one carries its rules and artwork inside the file and can be
sent to someone as-is.</p>
<table><thead><tr><th>When</th><th>Question</th><th class="k">Kind</th>
<th>Verdict</th><th>Export</th></tr></thead><tbody>{{ROWS}}</tbody></table>
<footer>Written by the Riftbound Oracle rules-report skill. Unofficial, and not
endorsed by, affiliated with, or sponsored by Riot Games. Rules text is Riot
Games' copyright.</footer>
</main></body></html>
"""


def _out_path(path, default_dir=None):
    """Resolve a caller-supplied output path against the caller's directory."""
    if os.path.isabs(path):
        return path
    return os.path.join(default_dir or CWD, path)


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
    # `-answer` only. Stripping `-primer` too was tidier and collided:
    # heron-answer.json and heron-primer.json both resolved to reports/heron.html,
    # so rendering one silently destroyed the other — a ruling and a primer about
    # the same subject is the NORMAL pairing, not an edge case.
    slug = os.path.splitext(os.path.basename(src))[0].replace("-answer", "")
    out = _out_path(explicit) if explicit else os.path.join(REPORTS, f"{slug}.html")
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
    # The same words the page uses. This printed the raw anchor id — "weakest
    # step: s2" — beside a page reading "Weakest link · transition 4", which is
    # the two halves describing one answer differently.
    what = ans.get("_weakest_label") or ans["_weakest"]
    print(f"weakest link: {what} in {ans['_weakest']} ({ans['_strength']})"
          if kind == "primer" else
          f"weakest link: {ans['_weakest']} ({ans['_strength']})")
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
        # Misconceptions carry citations too, so a narrowed one there printed
        # no `narrowed:` line — the id the author wrote was vaguer than the rule
        # that says the thing, and nothing said so.
        for m in ans.get("misconceptions", []) or []:
            if isinstance(m, dict):
                yield dict(m, id=f"misconception {m.get('belief', '')[:24]}")
    else:
        for note in ans.get("notes", []):
            yield note


def cmd_render(args):
    # Positionals separated from flags. `out = args[1]` bound `--force` as the
    # destination, so the documented escape hatch rendered to a path the caller
    # never named — the renderer then dropped the flag from its own positionals
    # and wrote report.html into the skill folder, reporting success.
    pos = [a for a in args if not a.startswith("-")]
    src = pos[0]
    out = _out_path(pos[1]) if len(pos) > 1 else _out_path("report.html")
    _v, _c, renderer = _verify_for(_kind(json.load(open(src, encoding="utf-8")), src))
    ensure_rulebook()
    # Flags are forwarded, not dropped: --force is the documented escape hatch
    # and it lives in the renderer, so swallowing it here made the flag a no-op
    # on the one path a caller reaches for it.
    subprocess.run([sys.executable, renderer, src, out]
                   + [a for a in args if a.startswith("-")], check=True)


FIREWORKS_HOMES = (
    "~/.claude/skills/fireworks-tech-graph",
    "~/.agents/skills/fireworks-tech-graph",
    "~/.config/agents/skills/fireworks-tech-graph",
)


def find_fireworks():
    """Locate a Fireworks Tech Graph install, or None.

    Deliberately soft. Fireworks lives OUTSIDE the skill folder, and ADR 0004
    says nothing here may depend on anything outside it — so the IR is what this
    project produces and stands behind, and rendering it is a bonus. A missing
    install costs a picture, never an answer, and `graph` still writes a
    document any Fireworks install can render later.

    $RIFTBOUND_FIREWORKS overrides, for an install somewhere else entirely.
    """
    # An override the caller SET is a statement, not a hint. Falling through to
    # the default search meant a single typo in $RIFTBOUND_FIREWORKS rendered
    # from a different install entirely and said nothing — or, on a machine with
    # no default install, reported "you have none" when what was wrong was the
    # spelling.
    override = os.environ.get("RIFTBOUND_FIREWORKS")
    if override:
        script = os.path.join(os.path.expanduser(override), "scripts", "fireworks.py")
        if not os.path.exists(script):
            raise SystemExit(
                f"$RIFTBOUND_FIREWORKS is set to {override!r}, but there is no\n"
                f"  scripts/fireworks.py under it. Fix the path or unset it to search\n"
                f"  the usual places: {', '.join(FIREWORKS_HOMES)}")
        return script
    for candidate in FIREWORKS_HOMES:
        script = os.path.join(os.path.expanduser(candidate), "scripts", "fireworks.py")
        if os.path.exists(script):
            return script
    return None


# Generous. A diagram is seconds of work; this exists so a renderer that wedges
# cannot wedge the command that called it, with no output and nothing to read.
RENDER_TIMEOUT = 120


def _renderer_said(run):
    """Whatever the renderer actually complained with.

    `run.stdout or run.stderr` picks stdout whenever it is truthy, and
    whitespace is truthy — a renderer that prints blank lines to stdout and its
    real traceback to stderr produced "could not render it: " with nothing after
    the colon, and the reason the user needed was discarded.
    """
    for stream in (run.stderr, run.stdout):
        text = (stream or "").strip()
        if text:
            return text[:300]
    return f"no output; exit code {run.returncode}"


def _looks_like_svg(path):
    """Is there a whole SVG at this path?

    Deliberately shallow — this is not an SVG validator, and it is not trying to
    be. It answers the one question the exit code cannot: did the renderer
    finish. A truncated file has no closing tag, and that is the failure this
    catches.
    """
    try:
        if os.path.getsize(path) < 64:
            return False
        with open(path, "rb") as fh:
            head = fh.read(512).lstrip()
            fh.seek(max(0, os.path.getsize(path) - 512))
            tail = fh.read()
    except OSError:
        return False
    return head.startswith(b"<") and b"<svg" in head and b"</svg>" in tail


def _discard(path):
    """Remove a staging file, and never fail because of it."""
    try:
        if os.path.exists(path):
            os.remove(path)
    except OSError:
        pass


def _write_atomically(path, write):
    """Write beside the destination, then move it into place.

    `open(path, "w")` truncates before the first byte is written, so a failure
    part-way destroys whatever was already there. The ruling and primer
    renderers learned this the hard way; anything that writes an artifact here
    does it the same way.
    """
    tmp = path + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as fh:
            write(fh)
        os.replace(tmp, path)
    except BaseException:
        _discard(tmp)
        raise


def cmd_graph(args):
    """Emit a primer's step graph for something else to draw.

    Derived from the same verified transitions the report draws, so a diagram
    produced from this cannot assert an edge the document does not. That is the
    point of having it: a website, a deck or a restyling pass works from the
    graph, never from a fresh reading of the prose.

        graph <primer.json>                    Fireworks IR, and an SVG if it is installed
        graph <primer.json> out.svg            same, named
        graph <primer.json> --format=mermaid   Mermaid source instead

    Fireworks is the default because it draws these far better than anything
    here would, and it is safe to use because it takes a structured document
    rather than a prompt — no description of the procedure is handed to
    anything. Mermaid stays because GitHub renders it inline in markdown, which
    an SVG cannot do.
    """
    src = args[0]
    fmt = "fireworks"
    for a in args[1:]:
        if a.startswith("--format="):
            fmt = a.split("=", 1)[1].strip().lower()
    if fmt not in ("fireworks", "mermaid"):
        raise SystemExit(f"unknown --format={fmt}; use fireworks or mermaid")

    raw = json.load(open(src, encoding="utf-8"))
    if _kind(raw, src) != "primer":
        raise SystemExit(f"{src}: `graph` needs a primer — a ruling has no step graph.")
    # Verified first. Emitting the graph from an unchecked file would hand a
    # website a diagram this project never stood behind.
    from render_primer import verify_primer
    ans = verify_primer(raw, _idx())
    if ans["_problems"]:
        print("VERIFICATION FAILED — not emitting a graph:", file=sys.stderr)
        for pb in ans["_problems"]:
            print(f"  ! {pb}", file=sys.stderr)
        sys.exit(1)

    explicit = next((a for a in args[1:] if not a.startswith("-")), None)
    slug = os.path.splitext(os.path.basename(src))[0].replace("-primer", "")

    if fmt == "mermaid":
        import flowgraph
        text = flowgraph.mermaid(ans["steps"], ans.get("topic", "Procedure"))
        if explicit:
            dest = _out_path(explicit)
            with open(dest, "w", encoding="utf-8") as fh:
                fh.write(text)
            print(f"wrote {dest}")
        else:
            print(text, end="")
        return

    import fireworks_ir
    ir = fireworks_ir.build(ans)
    svg_out = _out_path(explicit) if explicit else os.path.join(DIAGRAMS, f"{slug}.svg")
    ir_out = os.path.splitext(svg_out)[0] + ".fireworks.json"
    os.makedirs(os.path.dirname(os.path.abspath(ir_out)), exist_ok=True)
    _write_atomically(ir_out, lambda fh: (json.dump(ir, fh, indent=1, ensure_ascii=False),
                                          fh.write("\n")))
    print(f"wrote {ir_out}")
    print(f"  {len(ir['nodes'])} nodes, {len(ir['arrows'])} arrows, style {ir['style']}")

    fireworks = find_fireworks()
    if not fireworks:
        print(f"\nno Fireworks Tech Graph install found, so {os.path.basename(svg_out)} "
              "was NOT written.\n"
              "The IR above is complete and any install can render it:\n"
              f"  python3 <fireworks>/scripts/fireworks.py render architecture "
              f"{ir_out} {svg_out}\n"
              "  (npx skills add yizhiyanhua-ai/fireworks-tech-graph, or set "
              "$RIFTBOUND_FIREWORKS)")
        # Exit 0 only when the destination was OURS to choose. A caller who
        # named `out.svg` and did not get one did not get what they asked for,
        # and a green exit code says they did.
        sys.exit(1 if explicit else 0)
    # Rendered BESIDE the destination, then moved into place — never straight
    # over it. The renderer is not ours and may do anything on the way out: a
    # stub that writes half a file and exits 1 left a 36-byte fragment where a
    # 19,868-byte diagram had been, and the destination then looked like an
    # artifact. Invariant 10: a failure never leaves a stale artifact looking
    # current. The ruling and primer renderers already write this way; this is
    # the same rule applied to a renderer we do not control.
    staged = svg_out + ".rendering"
    try:
        run = subprocess.run([sys.executable, fireworks, "render", "architecture",
                              ir_out, staged], capture_output=True, text=True,
                             timeout=RENDER_TIMEOUT)
    except subprocess.TimeoutExpired:
        _discard(staged)
        print(f"\nFireworks did not finish within {RENDER_TIMEOUT}s and was stopped. "
              f"The IR at {ir_out} is complete; render it yourself to see why.",
              file=sys.stderr)
        sys.exit(1)
    complaint = _renderer_said(run)
    if run.returncode != 0 or not _looks_like_svg(staged):
        _discard(staged)
        # The EXIT CODE IS NOT THE ARTIFACT. A renderer that writes `<svg><g>`
        # and exits 0 was reported as "wrote out.svg", and neither the suite nor
        # the mutation battery noticed — an unclosed fragment no viewer will
        # open, announced as a success. What is on disk is checked instead.
        #
        # Reported, not paraphrased: the renderer's own message says more than
        # anything restated here.
        print(f"\nFireworks could not render it: {complaint}", file=sys.stderr)
        sys.exit(1)
    os.replace(staged, svg_out)
    print(f"wrote {svg_out}")


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


def _report_records():
    """Every report on disk, newest first, with what it is and when.

    Reads the rendered files rather than a sidecar index. An index that is
    written alongside reports goes stale the moment someone deletes one by
    hand, and then the history lies about what you have — the browser would
    list a report that is not there. The directory IS the history.
    """
    import html as _html
    out = []
    if not os.path.isdir(REPORTS):
        return out
    for name in os.listdir(REPORTS):
        if not name.endswith(".html") or name == INDEX_NAME:
            continue
        path = os.path.join(REPORTS, name)
        try:
            with open(path, encoding="utf-8", errors="replace") as fh:
                head = fh.read(20000)
                # The portable marker sits at the END — the embedded rulebook
                # is appended after the overlay's iframe, ~2.5MB into a 2.6MB
                # file. Read the tail for it rather than the head, or the flag
                # is never true and the column silently means nothing.
                fh.seek(0, os.SEEK_END)
                size = fh.tell()
                fh.seek(max(0, size - 400_000))
                tail = fh.read()
        except (OSError, ValueError):
            continue
        title = re.search(r"<title>(.*?)</title>", head, re.S)
        disp = re.search(r'class="disp[^"]*">([A-Z]+)<', head)
        out.append({
            "file": name,
            "title": _html.unescape(title.group(1).strip()) if title else name,
            "kind": "primer" if "primer" in head[:4000].lower() else "ruling",
            "disposition": disp.group(1) if disp else "",
            "mtime": os.path.getmtime(path),
            "size": os.path.getsize(path),
            "portable": 'id="rb-doc"' in head or 'id="rb-doc"' in tail,
        })
    return sorted(out, key=lambda r: r["mtime"], reverse=True)


def cmd_reports(args):
    """List what has been answered, and write a browsable index beside it."""
    import datetime
    records = _report_records()
    if not records:
        print(f"no reports yet in {REPORTS}")
        return 0
    for r in records:
        when = datetime.datetime.fromtimestamp(r["mtime"]).strftime("%Y-%m-%d %H:%M")
        flag = " [portable]" if r["portable"] else ""
        print(f"{when}  {r['kind']:6} {r['disposition']:9} {r['file']}{flag}")
        print(f"                          {r['title'][:76]}")
    index = write_report_index(records)
    print(f"\n{len(records)} report(s) — browse them at {index}")
    return 0


def write_report_index(records=None):
    """The history page. Regenerated from the directory on every call."""
    import datetime, html as _html
    records = _report_records() if records is None else records
    rows = []
    for r in records:
        when = datetime.datetime.fromtimestamp(r["mtime"]).strftime("%Y-%m-%d %H:%M")
        rows.append(
            f'<tr><td class="w">{when}</td>'
            f'<td><a href="./{_html.escape(r["file"])}">{_html.escape(r["title"])}</a></td>'
            f'<td class="k">{r["kind"]}</td>'
            f'<td class="d">{_html.escape(r["disposition"])}</td>'
            f'<td class="w">{"portable" if r["portable"] else ""}</td></tr>'
        )
    doc = REPORT_INDEX_HTML.replace("{{ROWS}}", "".join(rows)).replace(
        "{{COUNT}}", str(len(records)))
    path = os.path.join(REPORTS, INDEX_NAME)
    os.makedirs(REPORTS, exist_ok=True)
    _write_atomically(path, lambda fh: fh.write(doc))
    return path


def cmd_export(args):
    """Rebuild a report as ONE portable file, or refuse and write nothing."""
    import corpus
    import export_report
    if not args:
        sys.exit("usage: export <report.html> [out.html]")
    src = _out_path(args[0]) if not os.path.isabs(args[0]) else args[0]
    if not os.path.exists(src):
        alt = os.path.join(REPORTS, os.path.basename(args[0]))
        if os.path.exists(alt):
            src = alt
        else:
            sys.exit(f"no such report: {args[0]}")
    explicit = args[1] if len(args) > 1 and not args[1].startswith("-") else None
    stem = os.path.splitext(os.path.basename(src))[0]
    out = _out_path(explicit) if explicit else os.path.join(REPORTS, f"{stem}.portable.html")

    html = open(src, encoding="utf-8").read()
    rules_html = open(corpus.rulebook_html_path(), encoding="utf-8").read()
    try:
        doc = export_report.export(html, rules_html)
    except export_report.ExportRefused as err:
        print(f"EXPORT REFUSED — nothing written: {err}")
        return 1
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    _write_atomically(out, lambda fh: fh.write(doc))
    mb = len(doc.encode("utf-8")) / 1_000_000
    print(f"wrote {out}  ({mb:.1f} MB, self-contained)")
    print("Every rule it cites and every card image travel inside the file. "
          "Send it as-is.")
    write_report_index()
    return 0


COMMANDS = {"rule": cmd_rule, "section": cmd_section, "grep": cmd_grep,
            "card": cmd_card, "verify": cmd_verify, "render": cmd_render,
            "build": cmd_build, "selftest": cmd_selftest, "report": cmd_report,
            "mutants": cmd_mutants, "graph": cmd_graph,
            "rulebook": cmd_rulebook,
            "export": cmd_export, "reports": cmd_reports}


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
