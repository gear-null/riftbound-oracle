#!/usr/bin/env python3
"""Tests for the rule that decides which mutation batteries CI runs.

WHY THIS FILE EXISTS SEPARATELY

`battery-triggers.py` is the only thing standing between a push and a 40-minute
proof it may not need — and, in the other direction, between a changed skill
and the battery that is supposed to re-prove it. A rule that skips work is a
rule that can skip the wrong work, silently, and the failure mode is invisible:
CI stays green because the check that would have gone red never ran.

Which is this project's own standard applied to the workflow — a check nobody
has watched fail is not yet a check. So every clause of the rule is exercised
here, including the two directions that cost something real: a skill change
that must NOT be skipped, and a docs change that must NOT drag both batteries
along with it.

    python3 scripts/battery-triggers-test.py
"""
import importlib.util
import pathlib
import subprocess
import sys

HERE = pathlib.Path(__file__).resolve().parent
SCRIPT = HERE / "battery-triggers.py"

RAN = [0]
FAILED = []


def check(name, ok, detail=""):
    RAN[0] += 1
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}{'  — ' + detail if detail else ''}")
    if not ok:
        FAILED.append(name)


def load():
    spec = importlib.util.spec_from_file_location("battery_triggers", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def main():
    print("battery triggers — rule tests\n")
    t = load()

    def decide(*paths):
        verdict, _ = t.decide(list(paths))
        return verdict[t.RULES_REPORT], verdict[t.DECK_LAB]

    # --- the four shapes a push actually takes ------------------------------
    check("a docs-only change runs no battery",
          decide("docs/maintaining.md", "README.md", "docs/adr/0009-x.md") == (False, False))

    check("a deck-lab change runs only deck-lab's battery",
          decide(".claude/skills/deck-lab/lib/table.py") == (False, True))

    check("a rules-report change runs only rules-report's battery",
          decide(".claude/skills/rules-report/lib/verify_citations.py") == (True, False))

    check("a change touching both skills runs both",
          decide(".claude/skills/deck-lab/lib/table.py",
                 ".claude/skills/rules-report/lib/corpus.py") == (True, True))

    # The engine is the bulk of deck-lab's mutants and lives a few levels down;
    # a prefix rule that only matched lib/ directly would skip exactly the work
    # that made this workflow slow enough to need splitting.
    check("a nested engine file still counts as a deck-lab change",
          decide(".claude/skills/deck-lab/lib/engine/goldens/vanilla.json") == (False, True))

    check("a gauntlet decklist counts as a deck-lab change",
          decide(".claude/skills/deck-lab/gauntlet/ahri.json") == (False, True))

    # --- the corpus the rules-report skill is built from --------------------
    for path in ("output/core-rules.md", "output/tournament-rules.md",
                 "output/rules.md", "output/cards-ogn.md"):
        check(f"{path} re-proves rules-report",
              decide(path) == (True, False))

    # Pulled tournament lists land in output/decks/ and feed the vault and the
    # site, not a battery — deck-lab plays against its own committed gauntlet.
    check("a pulled decklist runs no battery",
          decide("output/decks/ahri-nine-tailed-fox-brehamm-4a018e.json") == (False, False))

    # --- the generators -----------------------------------------------------
    # skill-data writes cards.json into BOTH skills from one fetch, so it can
    # move either skill's data. Getting this wrong re-proves half a change.
    for path in ("src/skill-data.ts", "src/errata.ts", "src/riftcodex.ts",
                 "src/normalize.ts", "manifests/card-overlays.yaml"):
        check(f"{path} re-proves both skills", decide(path) == (True, True))

    check("an unrelated pipeline file runs no battery",
          decide("src/print.ts", "src/vault.ts", "src/__tests__/vault.test.ts")
          == (False, False))

    # --- the shapes that must not cost 40 minutes ---------------------------
    # This PR's own shape. If this ever fails, a workflow edit re-proves two
    # skills it cannot possibly have changed.
    check("editing CI, the docs and this rule itself runs no battery",
          decide(".github/workflows/ci.yml", "docs/maintaining.md",
                 "scripts/battery-triggers.py", "scripts/battery-triggers-test.py")
          == (False, False))

    check("an empty diff runs no battery", decide() == (False, False))
    check("blank lines in the diff are ignored", decide("", "  ") == (False, False))

    # --- fail-safe ----------------------------------------------------------
    check("a skill with no rule here runs everything",
          decide(".claude/skills/draft-lab/lib/mutants.py") == (True, True))

    check("a file loose in .claude/skills/ runs everything",
          decide(".claude/skills/README.md") == (True, True))

    # A near-miss on a known skill name must not be read as that skill.
    check("a look-alike skill folder is not mistaken for a known one",
          decide(".claude/skills/deck-lab-old/lib/table.py") == (True, True))

    # --- the reasoning is reported, not just the verdict --------------------
    _, reasons = t.decide([".claude/skills/deck-lab/lib/table.py"])
    check("the decision says which rule fired and why",
          len(reasons) == 1 and "deck_lab" in reasons[0] and "table.py" in reasons[0],
          reasons[0] if reasons else "(no reasons)")

    # An engine commit touches 25 files under one rule. A line per file is a
    # log nobody reads, and the reason a rule fired is the only thing anyone
    # comes to this step for.
    _, grouped = t.decide(
        [f".claude/skills/deck-lab/lib/engine/f{i}.py" for i in range(30)])
    check("many files under one rule collapse to one line",
          len(grouped) == 1 and "+27 more" in grouped[0],
          grouped[0] if grouped else "(no reasons)")

    _, two = t.decide([".claude/skills/deck-lab/lib/table.py", "output/rules.md"])
    check("two rules firing are reported separately", len(two) == 2,
          " | ".join(two))

    # --- the contract with the workflow -------------------------------------
    # `needs.changes.outputs.rules-report` parses as a subtraction in a GitHub
    # expression and evaluates to 0, which is falsy — every battery would skip,
    # silently, forever. The keys have to stay dash-free.
    check("output keys survive a GitHub expression",
          all(k.replace("_", "").isalnum() for k in t.BATTERIES),
          ", ".join(t.BATTERIES))

    run = subprocess.run(
        [sys.executable, str(SCRIPT)],
        input=".claude/skills/deck-lab/lib/table.py\ndocs/x.md\n",
        capture_output=True, text=True)
    check("stdout is exactly what $GITHUB_OUTPUT expects",
          run.returncode == 0
          and run.stdout == "rules_report=false\ndeck_lab=true\n",
          repr(run.stdout))
    check("the reasoning goes to stderr, where it cannot corrupt the outputs",
          "table.py" in run.stderr)

    empty = subprocess.run([sys.executable, str(SCRIPT)], input="",
                           capture_output=True, text=True)
    check("an empty diff still writes both keys",
          empty.stdout == "rules_report=false\ndeck_lab=false\n", repr(empty.stdout))

    # --- the rule table describes paths that exist --------------------------
    # A rule naming a path that has been renamed away is a rule that will never
    # fire again, and nothing else would say so.
    repo = HERE.parent
    stale = [p for p, _, _ in t.RULES
             if not any(repo.glob(p if not p.endswith("/**") else p[:-3]))]
    check("every rule still names something in the repo", not stale, ", ".join(stale))

    print()
    if FAILED:
        print(f"FAILED {len(FAILED)} of {RAN[0]}: {', '.join(FAILED)}")
        sys.exit(1)
    print(f"all {RAN[0]} battery-trigger checks passed")
    sys.exit(0)


if __name__ == "__main__":
    main()
