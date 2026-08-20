"""Spike: parse the official Riftbound rules into an addressable rule tree.

The bet this validates: the rules are already a citable tree — every atomic
claim has a canonical id like 471.1.b.1 — so we should retrieve and cite RULES,
not text chunks. If parsing is reliable, mechanical citation verification
becomes possible.

Run:  python3 parse_rules.py [--json out.json]
"""
import re, json, sys, os
from collections import Counter

from corpus import source_corpus_dir

# Fallback only, and only when a document carries no date. Both documents used
# to derive their version from this ONE literal, which made the per-document
# corpus-stamp check vacuous by construction — CR and TR could never disagree,
# so a swapped or stale pair validated cleanly. Riot states the date in each
# document; read it.
RULES_VERSION = "2026-07-16"

_DATE = re.compile(r"Last Updated:?\s*(\d{4}-\d{2}-\d{2}|\d{1,2}/\d{1,2}/\d{4})", re.I)


def source_version(path):
    """The version Riot states inside a rules document.

    Riot writes `2026-07-16` in the Core Rules and `7/16/2026` in the Tournament
    Rules; both normalise to ISO. Raises rather than guessing: a wrong version
    reaches the masthead, the rulebook header and the copy-cite string a judge
    pastes into a dispute, and a silent fallback is how one literal came to
    stand for two independent documents.
    """
    with open(path, encoding="utf-8") as fh:
        head = fh.read(4000)
    m = _DATE.search(head)
    if not m:
        raise SystemExit(f"{os.path.basename(path)}: no 'Last Updated' date in the first 4KB — "
                         "refusing to stamp the corpus with a guess")
    raw = m.group(1)
    if "/" in raw:
        mth, day, yr = raw.split("/")
        return f"{yr}-{int(mth):02d}-{int(day):02d}"
    return raw


def docs():
    """The source markdown to parse. Resolved lazily, and only by `build`.

    This used to run at import time, which meant a skill copied out of the repo
    could not even *import* this module — taking the whole selftest down with
    it, though only two of its checks touch the parser. A standalone install
    answers questions from the vendored data and never needs this path.
    """
    raw = source_corpus_dir()
    cr, tr = f"{raw}/core-rules.md", f"{raw}/tournament-rules.md"
    return [
        ("CR", cr, source_version(cr)),
        ("TR", tr, source_version(tr)),
    ]

# A rule starts with a 3-digit section then optional .N / .a levels, then a dot.
RULE_RE = re.compile(r"^(\d{3}(?:\.[0-9a-z]+)*)\.\s*(.*)$")

# A wrapped cross-reference looks exactly like a rule definition once the line
# breaks. In tournament-rules.md line 710 ends "...during gameplay. See CR" and
# 711 begins "128. Privacy for information types." — a naive scanner invents a
# TR:128 that does not exist. The tell is the PREVIOUS line ending in a
# reference cue, so veto a "definition" that follows one.
REF_CUE_RE = re.compile(
    r"\b(?:"
    # A reference verb, optionally trailed by "also" / "rule(s)" / a doc code.
    r"(?:see|per|refer to|described in|defined in|according to)"
    r"(?:\s+also)?(?:\s+rules?)?(?:\s+(?:CR|TR))?"
    # Or a preposition, but ONLY when it governs an explicit rule reference.
    # Bare "in"/"to" must NOT veto: prose wraps on them constantly, and a
    # false veto SWALLOWS a genuine rule into the previous one — causing the
    # exact corruption this guard exists to prevent.
    r"|(?:in|to|under|from)\s+(?:rules?|CR|TR)"
    r")\s*$",
    re.IGNORECASE,
)
# Running-header table rows carry section titles: "| 416. | Recycle |"
HEADER_RE = re.compile(r"^\|\s*(\d{3})\.\s*\|\s*([^|]+?)\s*\|")
EXAMPLE_RE = re.compile(r"^\s*Examples?:\s*(.*)$")

# Riot writes examples two ways. `Example: <text>` is one illustration, wrapped
# across lines by the PDF. `Examples:` alone heads a LIST, each item on its own
# line and itself sometimes wrapped. Only the singular form was recognised, so
# ten rules absorbed Riot's illustrations into their normative text — and the
# verifier then accepted a quote of an example as a quote of the rule, which is
# a category error a judge would care about.
#
# Items cannot be split per line, because they wrap. They can be split on how
# the next line STARTS: a continuation begins lowercase or with punctuation,
# a new item begins with a capital or an opening quote.
_ITEM_START = re.compile(r"^[\"\u201c\u2018(]|^[A-Z0-9]")
# "See rule 416." / "See 416.1." / "See rule 107.5. Banishment"
XREF_RE = re.compile(r"[Ss]ee\s+(?:rule\s+|section\s+)?(\d{3}(?:\.[0-9a-z]+)*)")


def parent_of(rule_id: str):
    parts = rule_id.split(".")
    return ".".join(parts[:-1]) if len(parts) > 1 else None


def parse_doc(doc, path, version):
    lines = open(path, encoding="utf-8").read().split("\n")
    section_titles, rules, order = {}, {}, []
    cur = None            # current rule id
    cur_example = None    # accumulating example lines
    prev_content = ""     # last non-blank, non-table line — for the cue veto
    vetoed = []           # wrapped cross-refs we refused to treat as rules

    in_example_list = False

    def flush_example():
        nonlocal cur_example
        if cur and cur_example:
            text = " ".join(cur_example).strip()
            if text:
                rules[cur]["examples"].append(text)
        cur_example = None

    for n, raw_line in enumerate(lines, 1):
        line = raw_line.rstrip()

        # Running-header rows: harvest the section title, then drop.
        h = HEADER_RE.match(line)
        if h:
            section_titles.setdefault(h.group(1), h.group(2).strip())
            continue
        if line.startswith("|"):
            continue

        if not line.strip():
            # A blank line does NOT end an Example. The PDF breaks pages mid-
            # example, and treating that as a terminator appended the example's
            # tail to the RULE's text — 431.2.d picked up "randomizing it as
            # normal, then chooses an opponent to gain 1 point…". An Example
            # runs until the next rule definition or the next Example.
            continue

        m = RULE_RE.match(line)
        if m and REF_CUE_RE.search(prev_content):
            # A wrapped "See CR / 128. Privacy…" — continuation, not a definition.
            vetoed.append((n, line[:70]))
            if cur_example is not None:
                cur_example.append(line.strip())
            elif cur:
                rules[cur]["text"] += " " + line.strip()
            prev_content = line
            continue

        if m:
            flush_example()
            in_example_list = False
            rid, text = m.group(1), m.group(2).strip()
            # A REPEATED id is a wrapped cross-reference, never a second
            # definition — "…conduct listed in" / "704. Engaging in…" is one
            # sentence broken across a line. The cue heuristic alone cannot
            # catch every phrasing, so this structural signature backs it up.
            #
            # Crucially the text belongs to the rule we are CURRENTLY reading,
            # not to the earlier rule that owns the id. Appending it there
            # corrupted TR:704 with a sentence from 705.3.b.
            if rid in rules:
                vetoed.append((n, line[:70]))
                if cur_example is not None:
                    cur_example.append(line.strip())
                elif cur:
                    rules[cur]["text"] += " " + line.strip()
                prev_content = line
                continue
            rules[rid] = {
                "id": rid,
                "doc": doc,
                "version": version,
                "depth": rid.count(".") + 1,
                "parent": parent_of(rid),
                "section": rid.split(".")[0],
                "text": text,
                "examples": [],
                "line_start": n,
            }
            order.append(rid)
            cur = rid
            prev_content = line
            continue

        ex = EXAMPLE_RE.match(line)
        if ex:
            flush_example()
            head = ex.group(1).strip()
            # A bare `Examples:` introduces a list; the header itself is not an
            # example, and each following item is separate. Joining them would
            # manufacture a sentence Riot never published — which is exactly the
            # string a verbatim gate must never accept.
            cur_example = [head] if head else []
            in_example_list = not head
            prev_content = line
            continue

        # Continuation of whatever we're inside.
        if cur_example is not None:
            stripped = line.strip()
            if in_example_list and cur_example and _ITEM_START.match(stripped):
                flush_example()
                cur_example = [stripped]
                prev_content = line
                continue
            cur_example.append(stripped)
        elif cur:
            rules[cur]["text"] += " " + line.strip()
        prev_content = line

    flush_example()

    for rid, r in rules.items():
        r["text"] = re.sub(r"\s+", " ", r["text"]).strip()
        r["section_title"] = section_titles.get(r["section"]) or (
            rules.get(r["section"], {}).get("text", "")
        )
        # Cross-refs, excluding self-references.
        r["see_also"] = sorted({x for x in XREF_RE.findall(r["text"]) if x != rid})
    return rules, order, section_titles, vetoed


def sort_key(rule_id: str):
    """Document order: numeric segments numerically, letters after numbers."""
    out = []
    for seg in rule_id.split("."):
        out.append((0, int(seg), "") if seg.isdigit() else (1, 0, seg))
    return out


def main():
    all_rules, stats, all_vetoed, disorder = {}, {}, [], []
    for doc, path, version in docs():
        rules, order, titles, vetoed = parse_doc(doc, path, version)
        for rid, r in rules.items():
            all_rules[f"{doc}:{rid}"] = r
        stats[doc] = dict(rules=len(rules), sections=len(titles), order=len(order))
        all_vetoed += [(doc, *v) for v in vetoed]
        # FIDELITY CHECK: rule ids must ascend in document order. A fabricated
        # rule (a wrapped cross-reference read as a definition) lands wildly out
        # of sequence. Orphan/xref checks are structurally blind to this — a
        # fabricated depth-1 rule has no parent to orphan.
        for prev, nxt in zip(order, order[1:]):
            if sort_key(nxt) < sort_key(prev):
                disorder.append((doc, prev, nxt))

    rules_list = list(all_rules.values())
    depths = Counter(r["depth"] for r in rules_list)
    empty = [r for r in rules_list if not r["text"]]
    orphans = [
        r for r in rules_list
        if r["parent"] and f'{r["doc"]}:{r["parent"]}' not in all_rules
    ]
    with_ex = sum(1 for r in rules_list if r["examples"])
    with_xref = sum(1 for r in rules_list if r["see_also"])
    broken_xref = []
    for r in rules_list:
        for x in r["see_also"]:
            if f'{r["doc"]}:{x}' not in all_rules:
                broken_xref.append((r["id"], x))
    untitled = [r for r in rules_list if not r["section_title"]]

    print("=== parse results ===")
    for doc, s in stats.items():
        print(f"  {doc}: {s['rules']} rules, {s['sections']} section titles")
    print(f"  TOTAL: {len(rules_list)} rules")
    print()
    print("=== structure ===")
    for d in sorted(depths):
        print(f"  depth {d}: {depths[d]}")
    print(f"  with examples:   {with_ex}")
    print(f"  with cross-refs: {with_xref}")
    print()
    print("=== integrity (all should be ~0) ===")
    print(f"  empty text:        {len(empty)}")
    print(f"  orphaned parent:   {len(orphans)}")
    print(f"  broken cross-refs: {len(broken_xref)}")
    print(f"  missing section title: {len(untitled)}")
    print(f"  OUT-OF-ORDER ids (fabrication signal): {len(disorder)}")
    for doc, a, b in disorder[:5]:
        print(f"    {doc}: {a} -> {b}")
    print()
    print(f"=== vetoed wrapped cross-references ({len(all_vetoed)}) ===")
    for doc, ln, txt in all_vetoed:
        print(f"  {doc} line {ln}: {txt}")
    print("  (each would have become a fabricated rule under a naive scanner)")
    for r in empty[:3]:
        print(f"    empty: {r['doc']}:{r['id']}")
    for r in orphans[:3]:
        print(f"    orphan: {r['doc']}:{r['id']} -> parent {r['parent']}")
    for a, b in broken_xref[:5]:
        print(f"    xref: {a} -> {b} (not found)")

    print()
    print("=== spot check: 471.1.b.1 with ancestry ===")
    key = "CR:471.1.b.1"
    if key in all_rules:
        chain, cur = [], all_rules[key]
        while cur:
            chain.append(cur)
            p = cur["parent"]
            cur = all_rules.get(f"CR:{p}") if p else None
        for r in reversed(chain):
            print(f"  [{r['id']}] {r['text'][:110]}")
    else:
        print("  MISSING — parser bug")

    if "--json" in sys.argv:
        out = sys.argv[sys.argv.index("--json") + 1]
        json.dump(rules_list, open(out, "w", encoding="utf-8"), indent=1)
        print(f"\nwrote {len(rules_list)} rules -> {out} ({os.path.getsize(out)//1024} KB)")


if __name__ == "__main__":
    main()
