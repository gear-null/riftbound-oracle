#!/usr/bin/env python3
"""Are the promises in docs/invariants.md still pinned by checks that can fail?

Exits non-zero on a gap. This is the release gate: not "did the suite pass" but
"is every invariant held up by a check that has been observed to fail".
"""
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
LIB = os.path.join(HERE, "..", ".claude", "skills", "rules-report", "lib")
LIB = os.path.abspath(LIB)
sys.path.insert(0, LIB)

# Invariant -> fragments of the check names that pin it. Fragments, not whole
# names, so a reworded check does not silently drop out of its invariant.
INVARIANTS = {
    "1. A citation never reads verified unless its quote is in the cited rule, verbatim": [
        "verified verbatim", "spliced across a block boundary",
        "fabricated citation exits non-zero", "quote-less citation downgrades",
        "whitespace-only quote", "fabricated primer citation exits non-zero"],
    "2. A citation is attributed to the right rule and the right document": [
        "cited rule keeps its own quote", "ambiguous quote home",
        "normative text outranks", "rejects a CR rule cited as TR",
        "TR-only bare id is labelled TR"],
    "3. Every rule id the report shows exists in the corpus": [
        "considered_rejected id", "rules_checked id", "rule_sections",
        "legend entry names a symbol"],
    "4. The page never claims more support than the notes carry": [
        "grounded note with no citations", "span cannot claim more support",
        "gap note is the weakest link",
        "uncited transition fails verification",
        "reports structural as its weakest link"],
    "5. Card text is Riot's current text, or is marked as not being it": [
        "override the vendored card text", "EMPTY card index", "missing card",
        "fused extraction artifact", "fused artifact at the end",
        "mid-sentence is detected",
        # The detector's widening axes, each pinned by a mutant that collapses
        # it back toward the stripper. Unpinned, the pair silently becomes one
        # opinion asked twice.
        "capitalised keyword fused at the end", "mid-text capital seam",
        "comma or semicolon is detected", "two-letter fusion is detected"],
    "6. Riot's illustrations are never presented as normative rules": [
        "Examples list as normative text", "each item stands alone"],
    "7. Provenance matches the corpus it was verified against": [
        "read from the document, not hardcoded", "corpus stamp",
        "citation dates follow the corpus"],
    "8. A research tool never reports absence it did not establish": [
        "which exists", "rewritten query says so", "finds the rule holding both words",
        "points at where its content lives", "clause that reverses a rule",
        "gap STEP must list rules_checked", "gap TRANSITION must list rules_checked"],
    "9. The answer verified is the answer the caller asked for": [
        "refused, not substituted", "mistaken for the output path",
        "unknown `kind` is refused",
        "a mis-set override is refused",
        "naming an SVG that could not be produced is not reported as success"],
    "10. A failure never leaves a stale artifact looking current": [
        "failed write leaves the previous ruling intact",
        "rulebook render leaves the previous one intact",
        "committed rulebook matches", "crash inside render leaves the previous report intact",
        "committed diagram matches what this corpus now produces",
        "failed render leaves the previous diagram untouched",
        "clears up after itself rather than leaving a staging file",
        "a truncated render is not announced as a diagram",
        "a truncated committed SVG is detected",
        "drawing different arrows from its IR is detected",
        "leaves no page behind", "failed write leaves the previous primer intact"],
    "11. The corpus is structurally whole": [
        "matches the recorded corpus exactly", "orphaned parents",
        "rendered rulebook is in numeric id order"],
    # An arrow is absorbed at a glance and audited by nobody, so the diagram is
    # derived from the transitions the primer DECLARES — and a declared
    # transition must either cite a rule or openly downgrade the document's
    # min() confidence. "Cites" was the original wording and it was too strong:
    # an exit declared `structural` or `gap` carries no citation and still draws
    # its arrow, which is the honest concession, not a hole. These pin the
    # derivation in both directions.
    "12. A diagram draws exactly the transitions the document declares": [
        "one edge per declared transition", "one node per declared step",
        "lands on a step the primer declares", "numbered in the prose beside it",
        "draws no dashed arrow", "structural transition draws a dashed one",
        "names only real steps", "goto naming no step is refused",
        "refuses to emit a diagram for it too",
        # The invariant does not stop at the report. An exported diagram travels
        # to a website and a deck, away from the prose and the ✓ VERIFIED stamps.
        "every node in the export is a declared step",
        "cannot be placed is not exported",
        "exported arrows carry the same numbers as the prose",
        "every basis maps to an edge class",
        "exported in the failed class",
        "legend lists only the edge classes actually drawn",
        "carries its corpus version and says it is unofficial",
        "the IR is still written",
        "the report, the map and the export agree on every transition"],
}


def failures(out):
    """The [FAIL] lines in a selftest run.

    THE GATE'S OWN BLIND SPOT, and the reason this is a named function with a
    self-test below rather than three lines inside main(). The gate harvested
    [PASS] lines and ignored both the exit code and every [FAIL] line, so a
    failing check simply VANISHED from its invariant's hit count — an invariant
    pinned by two checks, one of them now red, reported "1 check / 1 proven",
    and the gate exited 0 announcing all twelve invariants were pinned. The one
    thing meant to block a release was structurally incapable of seeing a red
    suite.
    """
    return [n.strip() for n in
            re.findall(r"^\s*\[FAIL\]\s*(.+?)(?:\s+—.*)?$", out, re.M)]


def self_test():
    """Prove this gate can still see a failure, before it speaks for the suite.

    `mutants.py` cannot reach here — it sandboxes the SKILL folder, and this
    file is maintainer-side, outside it. So the mutation discipline the rest of
    the project runs on does not apply, and this stands in for it: synthetic
    output known to be red, asserted to be read as red. It runs on every
    invocation, because a gate that is only checked when someone remembers to
    check it is the gate that was broken for this long.
    """
    red = ("  [PASS] something fine\n"
           "  [FAIL] a check that is red  — with a detail\n"
           "  [FAIL] another red one\n"
           "FAILED 2 of 3: a check that is red, another red one\n")
    green = "  [PASS] something fine\n  [PASS] something else\n"
    problems = []
    if failures(red) != ["a check that is red", "another red one"]:
        problems.append(f"cannot read [FAIL] lines: {failures(red)}")
    if failures(green):
        problems.append(f"invents failures in a green run: {failures(green)}")
    if problems:
        sys.exit("check-invariants cannot see a failing suite:\n  "
                 + "\n  ".join(problems))


def main():
    self_test()
    import mutants
    run = subprocess.run([sys.executable, os.path.join(LIB, "selftest.py")],
                         capture_output=True, text=True, cwd=LIB)
    out = run.stdout
    names = [n.strip() for n in
             re.findall(r"^\s*\[PASS\]\s*(.+?)(?:\s+—.*)?$", out, re.M)]
    if not names:
        sys.exit("selftest produced no passing checks — run it directly and fix that first")

    failed = failures(out)
    if failed or run.returncode != 0:
        print(f"{len(failed)} check(s) FAILING — the gate cannot speak for a red suite:")
        for name in failed:
            print(f"  ! {name}")
        sys.exit(f"\nselftest exited {run.returncode}. Fix the suite, then run this again.")
    proven = {n for m in mutants.MUTANTS for n in names if m["expect"] in n}

    gaps = []
    print(f"{'INVARIANT':64}{'checks':>7}{'proven':>8}")
    print("-" * 79)
    for inv, frags in INVARIANTS.items():
        hits = [n for n in names if any(f in n for f in frags)]
        prov = [n for n in hits if n in proven]
        flag = ""
        if not hits:
            flag, _ = "  NO CHECKS", gaps.append((inv, "no check matches its fragments"))
        elif len(prov) < len(hits):
            flag = "  UNPROVEN"
            gaps.append((inv, ", ".join(n for n in hits if n not in prov)))
        print(f"{inv[:62]:64}{len(hits):>7}{len(prov):>8}{flag}")
    print("-" * 79)
    print(f"suite: {len(proven)}/{len(names)} checks proven "
          f"({100 * len(proven) // len(names)}%) by {len(mutants.MUTANTS)} mutants")

    if gaps:
        print()
        for inv, why in gaps:
            print(f"GAP  {inv}\n     {why}")
        sys.exit(f"\n{len(gaps)} invariant(s) not fully pinned — see docs/invariants.md")
    print(f"\nall {len(INVARIANTS)} invariants pinned by checks that have been seen to fail")


if __name__ == "__main__":
    main()
