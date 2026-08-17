#!/usr/bin/env python3
"""Mutation battery — proves the selftest can actually fail.

WHY THIS EXISTS

Seven rounds of review on this skill found the same thing twice, and the second
time it was the dominant category: **checks that could not fail**. A legend
check that harvested its tokens from the page and compared them against that
same page. A probe satisfied by the explanatory comment sitting above the rule
it was probing for. An `all()` over a collection nobody asserted was non-empty.
An assertion that an identifier appears in source text, which passes whether or
not the code is ever called.

Every one of those was green while the exact defect it was named for was live.
The suite's headline number kept growing and its meaning did not.

So: a check that has never been observed to fail is not yet a check. This file
reintroduces each defect the suite claims to catch, runs the suite against the
damaged copy, and asserts the right check goes red. A mutant that SURVIVES is a
check that is lying.

Usage:  python3 rules_cli.py mutants
        python3 mutants.py            (same thing)

Nothing here touches the working tree — every mutant is applied to a throwaway
copy of the whole skill folder. That is not fastidiousness: an earlier review
sweep ran a truncating build whose output path resolved back to the real
`data/rules.html` and destroyed it.
"""
import os
import re
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL = os.path.dirname(HERE)


# Each mutant: reintroduce ONE defect, name the check that must catch it.
# `regen` rebuilds the rulebook after mutating, for defects that only show up in
# the generated artifact.
MUTANTS = [
    # ---- the verbatim gate itself -------------------------------------------
    # The round-6 regression exactly: BOTH the joined haystack and the joined
    # narrowing text. Either half alone is caught by the other, so a one-sided
    # mutant survives while proving nothing.
    dict(name="reintroduce the round-6 joined haystack AND joined narrowing",
         file="verify_citations.py",
         find="quote_ok = any(needle in norm(p) for p in idx.subtree_parts(rule_id, doc))",
         repl="quote_ok = needle in norm(' '.join(idx.subtree_parts(rule_id, doc)))",
         also=('            own = [r for r in scope if needle in norm(r["text"])]\n'
               '            if not own:\n'
               '                own = [r for r in scope\n'
               '                       if any(needle in norm(e) for e in r.get("examples", []))]',
               '            own = [r for r in scope\n'
               '                   if needle in norm(" ".join([r["text"]] + list(r.get("examples", []))))]'),
         expect="spliced across a block boundary"),
    dict(name="rank Examples equal to normative text when narrowing",
         file="verify_citations.py",
         find='            own = [r for r in scope if needle in norm(r["text"])]\n'
              '            if not own:\n'
              '                own = [r for r in scope\n'
              '                       if any(needle in norm(e) for e in r.get("examples", []))]',
         repl='            own = [r for r in scope\n'
              '                   if needle in norm(" ".join([r["text"]] + list(r.get("examples", []))))]',
         expect="normative text outranks an Example"),
    dict(name="drop descendants' Examples from the subtree",
         file="verify_citations.py",
         find="            parts.extend(x.get(\"examples\", []))",
         repl="            parts.extend(x.get(\"examples\", []) if x[\"id\"] == r[\"id\"] else [])",
         expect="descendant Example verifies at every ancestor"),
    dict(name="accept a citation whose quote was never checked",
         file="render_report.py",
         find="    return res.ok and res.checked",
         repl="    return res.ok",
         expect="quote-less citation downgrades its note"),

    # ---- claims the page makes ----------------------------------------------
    dict(name="let a grounded note assert with no citation",
         file="render_report.py",
         find='        if note["basis"] == "grounded" and not note.get("cites"):',
         repl="        if False:",
         expect="grounded note with no citations"),
    dict(name="exclude gap notes from the weakest link",
         file="render_report.py",
         find="    graded = notes",
         repl='    graded = [n for n in notes if n["basis"] != "gap"] or notes',
         expect="gap note is the weakest link"),
    dict(name="let a span out-rank the note it points at",
         file="render_report.py",
         find='        if note and RANK.get(sp.get("basis"), 0) > RANK.get(note.get("basis"), 0):',
         repl="        if False:",
         expect="span cannot claim more support"),
    dict(name="stop verifying considered_rejected ids",
         file="render_report.py",
         find="        found = idx.get(crid, cdoc) or idx.get(crid, None)",
         repl='        found = idx.get(crid, cdoc) or idx.get(crid, None) or {"doc": cdoc or "CR"}',
         expect="fabricated considered_rejected id"),
    dict(name="stop verifying rules_checked ids",
         file="render_report.py",
         find="            if not rrid or not idx.get(rrid, rdoc):",
         repl="            if False:",
         expect="fabricated rules_checked id"),
    dict(name="allow duplicate note ids",
         file="render_report.py",
         find="    if _dupes:",
         repl="    if False:",
         expect="duplicate note ids"),
    dict(name="let answer fields override the vendored card record",
         file="render_report.py",
         find="            for k, v in supplied.items():\n"
              "                if not v or resolved.get(k):\n"
              "                    continue",
         repl="            for k, v in supplied.items():\n"
              "                if not v:\n"
              "                    continue",
         expect="card"),
    dict(name="report an empty card index as a missing card",
         file="render_report.py",
         find='    if bridge is not None and not getattr(bridge, "cards", None):',
         repl="    if False:",
         expect="EMPTY card index"),

    # ---- provenance ----------------------------------------------------------
    dict(name="hardcode the rules date in the copy-cite string",
         file="render_report.py",
         find='    dated = corpus.get(doc) or "version unstated"',
         repl='    dated = "2026-07-16"',
         expect="citation dates follow the corpus"),
    dict(name="name the narrowing destination instead of the origin",
         file="render_report.py",
         find='    c["narrowed"] = rid if res.narrowed_to else None',
         repl='    c["narrowed"] = res.narrowed_to',
         expect="names where it came FROM"),

    # ---- the legend ----------------------------------------------------------
    dict(name="let <script> bodies feed the symbol legend",
         file="render_report.py",
         find='body = re.sub(r"<(script|style)\\b.*?</\\1>", " ", page_html, flags=re.S | re.I)',
         repl='body = re.sub(r"<(script)\\b.*?</\\1>", " ", page_html, flags=re.S | re.I)',
         expect="style bodies do not reach the legend"),

    # ---- the printed page ----------------------------------------------------
    dict(name="drop the light canvas from the rulebook print sheet",
         file="render_rulebook.py",
         find="color-scheme:light;",
         repl="",
         expect="print sheet declares a light canvas"),
    dict(name="remap a print token to something illegible on white",
         file="render_report.py",
         find=" --gold-500:var(--gold-700);",
         repl=" --gold-500:var(--mist-100);",
         expect="legible on white"),

    # ---- the rulebook artifact ----------------------------------------------
    dict(name="emit the rulebook in raw input order",
         file="render_rulebook.py",
         find="    for d in by_doc:\n        by_doc[d].sort(key=lambda r: id_sort_key(r[\"id\"]))",
         repl="    pass",
         expect="rendered rulebook is in numeric id order",
         regen=True),
    dict(name="truncate the rulebook before rendering it",
         file="render_rulebook.py",
         find="    page = render_rulebook(rules, version)\n    tmp = out + \".tmp\"",
         repl="    open(out, \"w\").close()\n    page = render_rulebook(rules, version)\n    tmp = out + \".tmp\"",
         expect="crash inside the rulebook render"),

    # ---- the CLI contract ----------------------------------------------------
    dict(name="bind --force as the positional output path",
         file="render_report.py",
         find='    pos = [a for a in sys.argv[1:] if not a.startswith("--")]\n'
              '    src = pos[0] if pos else "answer.json"\n'
              '    out = pos[1] if len(pos) > 1 else "report.html"',
         repl='    src = sys.argv[1] if len(sys.argv) > 1 else "answer.json"\n'
              '    out = sys.argv[2] if len(sys.argv) > 2 else "report.html"',
         expect="mistaken for the output path"),
    dict(name="let a rail claim render unclipped",
         file="render_report.py",
         find='    cut = text.rfind(" ", 0, limit)\n'
              '    return text[:cut if cut > 0 else limit].rstrip(" ,;:—-") + "…"',
         repl='    return text[:text.rfind(" ", 0, limit)].rstrip(" ,;:—-") + "…"',
         expect="shortened even with no early space"),
]

FAILED_RE = re.compile(r"^FAILED \d+ of \d+: (.*)$", re.M)


def run_one(m):
    """Apply one mutant to a throwaway copy and report which checks caught it."""
    with tempfile.TemporaryDirectory() as d:
        skill = os.path.join(d, "rules-report")
        shutil.copytree(SKILL, skill, ignore=shutil.ignore_patterns(
            "reports", "__pycache__", "*.db", "*.tmp"))
        lib = os.path.join(skill, "lib")
        path = os.path.join(lib, m["file"])
        src = open(path, encoding="utf-8").read()
        if src.count(m["find"]) != 1:
            return None, (f"anchor matched {src.count(m['find'])}x — the mutant is "
                          "stale and is testing nothing")
        src = src.replace(m["find"], m["repl"])
        if m.get("also"):
            find2, repl2 = m["also"]
            if src.count(find2) != 1:
                return None, "second anchor did not match — the mutant is stale"
            src = src.replace(find2, repl2)
        open(path, "w", encoding="utf-8").write(src)

        if m.get("regen"):
            subprocess.run([sys.executable, os.path.join(lib, "rules_cli.py"), "rulebook"],
                           capture_output=True, text=True, cwd=lib)

        r = subprocess.run([sys.executable, os.path.join(lib, "selftest.py")],
                           capture_output=True, text=True, cwd=lib)
        hit = FAILED_RE.search(r.stdout)
        if hit:
            return [s.strip() for s in hit.group(1).split(",")], None
        if r.returncode != 0:
            # No verdict line and a non-zero exit: the suite died rather than
            # reporting. Detection, not survival.
            last = [x for x in r.stderr.strip().splitlines() if x.strip()]
            return ["<suite crashed> " + (last[-1] if last else "no output")], None
        return [], None


def main():
    print("mutation battery — reintroducing defects the suite claims to catch\n")
    survived, stale = [], []
    for i, m in enumerate(MUTANTS, 1):
        failures, err = run_one(m)
        if err:
            stale.append((m["name"], err))
            print(f"  [STALE] {i:2}. {m['name']}\n           {err}")
            continue
        crashed = [f for f in failures if f.startswith("<suite crashed>")]
        caught = [f for f in failures if m["expect"] in f]
        if crashed and not caught:
            print(f"  [crashed] {i:2}. {m['name']}")
            print(f"            {crashed[0][:110]}")
            print("            detected, but as a crash rather than a named failure")
        elif caught:
            print(f"  [caught] {i:2}. {m['name']}")
        else:
            survived.append(m)
            print(f"  [SURVIVED] {i:2}. {m['name']}")
            print(f"             expected a check matching {m['expect']!r}")
            print(f"             got: {failures or 'NOTHING — the suite stayed green'}")

    print()
    if stale:
        print(f"{len(stale)} mutant(s) no longer apply — update them; they prove nothing as-is.")
    if survived:
        print(f"FAILED: {len(survived)} of {len(MUTANTS)} mutants survived.")
        print("A surviving mutant means the named check passes while its defect is live.")
        sys.exit(1)
    print(f"all {len(MUTANTS)} mutants caught — every check named here has been "
          "observed to fail.")
    sys.exit(0)


if __name__ == "__main__":
    main()
