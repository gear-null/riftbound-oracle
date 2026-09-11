#!/usr/bin/env python3
"""Decide which mutation batteries a change has to re-prove.

WHY THIS FILE EXISTS

Each skill ships a mutation battery — `mutants.py` — that reintroduces every
defect the suite claims to catch and asserts the named check goes red. They are
the slowest thing in CI by an order of magnitude: measured on the run that
merged #55, rules-report's battery took 31.7 minutes and deck-lab's 7.2, while
every other step in the whole workflow finished inside a minute. Running both
on every push meant ~40 minutes of wall clock before any PR could go green,
most of it re-proving a skill the push had not touched.

A battery only says something about the skill it mutates, so it only needs to
run when that skill — or an input that changes what the skill ships — moved.
This file is where that rule lives, as data rather than as `paths:` filters in
the workflow, for three reasons:

  * a workflow-level `paths:` filter would skip the whole job, which changes
    what a required check reports; branch protection then blocks forever on a
    check that never runs. Deciding inside the job keeps every check name
    reporting on every push.
  * a PR that touches both skills has to run both, which a per-job filter
    cannot express.
  * a rule with a test beside it (`battery-triggers-test.py`) is a rule that has
    been seen to fail. A `paths:` filter is only ever proven in production.

Reads changed paths, one per line, on stdin. Writes GITHUB_OUTPUT-shaped
decisions on stdout and the reasoning on stderr:

    git diff --name-only "$BASE_SHA...HEAD" | python3 scripts/battery-triggers.py
    rules_report=false
    deck_lab=true

The caller — `.github/workflows/ci.yml` — runs BOTH batteries whenever it
cannot work out a base commit to diff against, so a broken or missing diff
costs 40 minutes rather than skipping a proof.
"""
import fnmatch
import sys

# Output keys. Underscores, not dashes: `needs.changes.outputs.rules-report`
# parses as a subtraction in a GitHub expression and silently evaluates to 0.
RULES_REPORT = "rules_report"
DECK_LAB = "deck_lab"
BATTERIES = (RULES_REPORT, DECK_LAB)

# Every rule is (pattern, batteries, why). `dir/**` matches everything under
# that directory; anything else is a glob against the whole path.
#
# The reason column is not decoration — it is what a reader checks a new rule
# against. "Would changing this file change what the battery proves?" If no,
# the rule does not belong here, because every rule costs wall clock on pushes
# that did not need it.
RULES = (
    (".claude/skills/rules-report/**", (RULES_REPORT,),
     "the skill its battery mutates"),
    (".claude/skills/deck-lab/**", (DECK_LAB,),
     "the skill its battery mutates"),

    # The corpus the rules-report skill is built from. `rules_cli.py build`
    # parses core-rules.md and tournament-rules.md into data/rules.json, and
    # `oracle skill-data` folds the `[NEW TEXT]` errata blocks in rules.md and
    # the per-set card text into data/cards.json. Moving any of them moves what
    # the suite is checking, so the checks have to be re-proven against it.
    ("output/core-rules.md", (RULES_REPORT,), "the rulebook the skill parses"),
    ("output/tournament-rules.md", (RULES_REPORT,), "the rulebook the skill parses"),
    ("output/rules.md", (RULES_REPORT,), "the errata folded into card text"),
    ("output/cards-*.md", (RULES_REPORT,), "the card text folded into cards.json"),

    # The generators. `skill-data` writes data/cards.json into BOTH skills from
    # one fetch (see CARD_DATA_TARGETS) precisely so the two cannot disagree
    # about what a card says — which means a change to that path can move
    # either skill's data, and both batteries owe an answer.
    ("src/skill-data.ts", BATTERIES, "generates both skills' cards.json"),
    ("src/errata.ts", BATTERIES, "generates both skills' cards.json"),
    ("src/riftcodex.ts", BATTERIES, "generates both skills' cards.json"),
    ("src/normalize.ts", BATTERIES, "generates both skills' cards.json"),
    ("manifests/card-overlays.yaml", BATTERIES, "hand-transcribed card text"),
)

# A skill folder nobody has written a rule for. A third skill will arrive with
# its own battery long before anyone remembers this file, and the safe default
# for an unrecognised skill is to run everything rather than to prove nothing.
SKILLS_ROOT = ".claude/skills/"
KNOWN_SKILL_DIRS = tuple(
    pattern[: -len("**")] for pattern, _, _ in RULES if pattern.startswith(SKILLS_ROOT)
)


def matches(pattern, path):
    if pattern.endswith("/**"):
        return path.startswith(pattern[: -len("**")])
    return fnmatch.fnmatchcase(path, pattern)


def decide(paths):
    """Which batteries the given changed paths require, and why.

    Returns ({battery: bool}, [reason lines]). Total: a path matching no rule
    contributes nothing, which is the entire point — a docs change proves
    nothing about a mutant. Reasons are one line per RULE that fired rather
    than per file, because an engine commit touches 25 files under one rule and
    a log nobody reads is not a log.
    """
    verdict = {battery: False for battery in BATTERIES}
    hits = {}
    unknown_skills = []
    for path in paths:
        path = path.strip()
        if not path:
            continue
        for index, (pattern, batteries, _why) in enumerate(RULES):
            if matches(pattern, path):
                for battery in batteries:
                    verdict[battery] = True
                hits.setdefault(index, []).append(path)
                break
        else:
            if path.startswith(SKILLS_ROOT) and not path.startswith(KNOWN_SKILL_DIRS):
                for battery in BATTERIES:
                    verdict[battery] = True
                unknown_skills.append(path)

    reasons = []
    for index, (pattern, batteries, why) in enumerate(RULES):
        if index in hits:
            reasons.append(
                f"{', '.join(batteries)} <- {pattern} ({why}): {summarise(hits[index])}")
    if unknown_skills:
        reasons.append(
            f"{', '.join(BATTERIES)} <- a skill with no rule in this file "
            f"(running everything rather than proving nothing): "
            f"{summarise(unknown_skills)}")
    return verdict, reasons


def summarise(paths, shown=3):
    head = ", ".join(paths[:shown])
    return head if len(paths) <= shown else f"{head}, +{len(paths) - shown} more"


def main():
    verdict, reasons = decide(sys.stdin.read().splitlines())
    for line in reasons or ["nothing changed that a mutation battery proves"]:
        print(f"  {line}", file=sys.stderr)
    for battery in BATTERIES:
        print(f"{battery}={'true' if verdict[battery] else 'false'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
