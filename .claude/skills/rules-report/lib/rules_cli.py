#!/usr/bin/env python3
"""`rules` — deterministic tools for answering Riftbound rules questions.

Architecture note. This deliberately does NOT do semantic retrieval over the
rules. That was measured and it failed: recall@10 of 32% over 620 real
questions, because 65% of questions name a card and only ~4% of card names
appear anywhere in rule text. Users ask in card vocabulary; the rules are
written in rules vocabulary, and no amount of BM25 tuning bridges that.

Instead the agent NAVIGATES. These commands are the primitives it navigates
with — each one exact, deterministic, and free of model judgement:

    rules card <name>       exact card lookup -> printed text + keywords + rule links
    rules rule <id>...      exact rule + ancestor spine + children + cross-refs
    rules grep <pattern>    lexical search over rule text (agent-driven, not RAG)
    rules section <id>      a whole numbered section, in document order
    rules report <json>     verify + render + open — the ONLY way to finish an answer
    rules verify <json>     mechanical citation gate (report runs this for you)
    rules selftest          regression harness; run after every rules update
    rules render <json>     interactive HTML report

The division of labour: the agent decides WHAT to look at, code decides whether
the citations it produced are real.
"""
import json, os, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

RULES_JSON = os.path.join(HERE, "rules.json")
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
        for k in sorted(kids, key=lambda x: x["id"]):
            print(f"   {'  ' * (k['depth'] - 1)}{k['id']}. {k['text']}")
        for ex in r.get("examples", []):
            print(f"   Example: {ex}")
        if r.get("see_also"):
            print(f"   see also: {', '.join(r['see_also'])}")
        print()


def cmd_section(args):
    idx = _idx()
    doc, sec = (args[0].split(":", 1) if ":" in args[0] else ("CR", args[0]))
    rows = [r for r in idx.rules.values() if r["doc"] == doc and r["section"] == sec]
    if not rows:
        print(f"no section {doc}:{sec}")
        return
    def key(r):
        out = []
        for s in r["id"].split("."):
            out.append((0, int(s), "") if s.isdigit() else (1, 0, s))
        return out
    for r in sorted(rows, key=key):
        print(f"{'  ' * (r['depth'] - 1)}{r['id']}. {r['text']}")


def cmd_grep(args):
    """Lexical search the agent drives itself. Not a retrieval pipeline."""
    from retrieve import Retriever
    limit = 12
    if "-n" in args:
        i = args.index("-n"); limit = int(args[i + 1]); args = args[:i] + args[i + 2:]
    r = Retriever(RULES_DB)
    for h in r.search(" ".join(args), limit):
        print(f"{h['uid']:18} [{h['section']}. {h['section_title'][:22]:24}] {h['text'][:110]}")


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
        if c.get("inexact"):
            print(f"!!! NO CARD NAMED '{c['asked_as']}' EXISTS.")
            print(f"    Closest name match is '{c['name']}', which is a DIFFERENT card.")
            print(f"    Do not reason about '{c['asked_as']}' from this text.")
        print(f"=== {c['name']} ===")
        print(f"  {c['text']}")
        print(f"  keywords : {', '.join(c['keywords']) or '(none printed)'}")
        print(f"  -> rules : {', '.join(c['rule_sections']) or '(no keyword maps to a rule section)'}")
        print()


def cmd_report(args):
    """Verify, render and open — one step, so an answer cannot be half-delivered.

    Splitting this into `verify` then `render` meant an answer could be left as
    a JSON file plus an instruction to run something. The user should never be
    handed homework; finishing an answer means producing the report.
    """
    src = args[0]
    explicit = args[1] if len(args) > 1 and not args[1].startswith("-") else None
    slug = os.path.splitext(os.path.basename(src))[0].replace("-answer", "")
    out = explicit or os.path.join(REPORTS, f"{slug}.html")
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)

    # Verify first; a failing gate must not silently produce a pretty report.
    from render_report import verify_answer
    ans = verify_answer(json.load(open(src, encoding="utf-8")), _idx())
    if ans["_problems"]:
        print("VERIFICATION FAILED — not rendering:")
        for pb in ans["_problems"]:
            print(f"  ! {pb}")
        sys.exit(1)

    subprocess.run([sys.executable, os.path.join(HERE, "render_report.py"), src, out], check=True)
    print(f"\nreport: {os.path.normpath(os.path.abspath(out))}")
    if "--no-open" not in args:
        opener = {"darwin": "open", "win32": "start"}.get(sys.platform, "xdg-open")
        try:
            subprocess.run([opener, out], check=False,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            print("opened in your browser")
        except Exception:
            pass


def cmd_verify(args):
    from render_report import verify_answer
    ans = json.load(open(args[0], encoding="utf-8"))
    ans = verify_answer(ans, _idx())
    nc = sum(len(n.get("cites", [])) for n in ans["notes"])
    nv = sum(1 for n in ans["notes"] for c in n.get("cites", []) if c["verified"])
    print(f"disposition : {ans['holding']['disposition']}"
          + (f"  (FORCED from {ans['holding']['_forced']})" if ans["holding"].get("_forced") else ""))
    print(f"citations   : {nv}/{nc} verified verbatim")
    print(f"weakest link: {ans['_weakest']} ({ans['_strength']})")
    for n in ans["notes"]:
        for c in n.get("cites", []):
            if c.get("narrowed"):
                print(f"  narrowed: {n['id']} {c['rule']} -> {c['cite_as']}")
    for p in ans["_problems"]:
        print(f"  ! {p}")
    sys.exit(1 if ans["_problems"] else 0)


def cmd_render(args):
    src = args[0]
    out = args[1] if len(args) > 1 else "report.html"
    subprocess.run([sys.executable, os.path.join(HERE, "render_report.py"), src, out], check=True)


def cmd_selftest(args):
    """Regression harness — run after every rules update."""
    # selftest's contract IS its exit code; discarding it reported a
    # post-update regression as success to anything checking $?.
    sys.exit(subprocess.run([sys.executable, os.path.join(HERE, "selftest.py")], cwd=HERE).returncode)


def cmd_build(args):
    subprocess.run([sys.executable, os.path.join(HERE, "parse_rules.py"),
                    "--json", RULES_JSON], check=True, cwd=HERE)
    subprocess.run([sys.executable, os.path.join(HERE, "retrieve.py"), "build"],
                   check=True, cwd=HERE)


COMMANDS = {"rule": cmd_rule, "section": cmd_section, "grep": cmd_grep,
            "card": cmd_card, "verify": cmd_verify, "render": cmd_render,
            "build": cmd_build, "selftest": cmd_selftest, "report": cmd_report}


def main():
    if len(sys.argv) < 2 or sys.argv[1] not in COMMANDS:
        print(__doc__)
        sys.exit(0 if len(sys.argv) < 2 else 2)
    os.chdir(HERE)
    COMMANDS[sys.argv[1]](sys.argv[2:])


if __name__ == "__main__":
    main()
