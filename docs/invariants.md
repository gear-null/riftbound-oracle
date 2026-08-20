# What must never be false

Ten review rounds on this skill found ~70 defects and never converged, because
the exit criterion was *"run a review, fix what it finds"* — which does not
terminate. This file is the replacement criterion.

Each statement below is something the product promises. Each is pinned by named
checks in `selftest.py`, and each of those checks is pinned by a mutant in
`mutants.py` that has been **observed to make it fail**. A check nobody has seen
fail is not evidence; two review rounds were spent discovering that the hard way.

Run both:

```bash
python3 .claude/skills/rules-report/lib/rules_cli.py selftest   # the properties hold
python3 .claude/skills/rules-report/lib/rules_cli.py mutants    # the checks can fail
```

`mutants` is slow — it runs the whole suite once per mutant, and the corpus ones
rebuild `rules.json` first. It is a pre-release gate, not an inner loop.

## The invariants

| # | Must never be false |
|---|---|
| 1 | A citation never reads *verified* unless its quote appears in the cited rule, verbatim |
| 2 | A citation is attributed to the right rule and the right document |
| 3 | Every rule id the report shows exists in the corpus |
| 4 | The page never claims more support than the notes carry |
| 5 | Card text is Riot's current text, or is marked as not being it |
| 6 | Riot's illustrations are never presented as normative rules |
| 7 | Provenance on the page matches the corpus it was verified against |
| 8 | A research tool never reports absence it did not establish |
| 9 | The answer verified is the answer the caller asked for |
| 10 | A failure never leaves a stale artifact looking current |
| 11 | The corpus is structurally whole |

Numbers 8 and 9 look like plumbing and are not. This skill is driven by an agent
that navigates with `rules_cli.py` and then writes an answer. A tool that
misleads it yields a wrong conclusion **cited correctly** — every downstream gate
passes, because the verifier checks that a quote is real, not that the reasoning
resting on it is sound. Round 8 found `grep` displaying the exact opposite of a
rule by clipping the sentence before its "not". Nothing downstream could catch
that.

## Adding one

When a defect escapes, do not just fix it:

1. Decide which invariant it violated. If none, that is a twelfth invariant —
   add the row.
2. Add a check that fails on the unfixed code.
3. Add a mutant that reintroduces the defect, and confirm the battery reports
   your check by name.

Step 3 is the one that matters. Of the checks written across ten rounds, several
passed while the defect they were named for was live: one compared the page
against itself, one asserted that an identifier appeared in source text, one
searched a whole document for a word every document contains. The battery found
all of them, and found three bugs in itself besides.

## The verification script

`scripts/check-invariants.py` prints the table with each invariant's check count
and how many of those checks are proven. It exits non-zero on a gap.

## What this is not

It is not a claim that the code is defect-free. Coverage of the whole suite is
about two thirds; the remainder is mostly cosmetic and is listed in
`docs/known-issues.md`. It is a claim that the eleven statements above are the
ones worth blocking a release on, and that each is currently held up by a check
that has been seen to fail.
