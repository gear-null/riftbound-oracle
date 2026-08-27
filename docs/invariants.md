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
| 12 | A diagram draws exactly the transitions the document declares — no more, no fewer |

Number 12 arrived with the primer, and it is the one that makes a picture
publishable. A diagram is the surface a reader trusts most and checks least: an
arrow is absorbed at a glance and never audited the way a sentence is. So the
graph is *derived* from the transitions the document has already declared, and
those checks assert the derivation both ways — every arrow drawn is a declared
transition, and every declared transition is drawn. There is no field in which
an author can add an edge.

*Declared*, not *cited*: an exit declared `structural` carries no citation and
still draws, paying for it in the document's `min()` confidence and in a dashed
stroke. What the invariant guarantees is that the picture says nothing the
document did not say out loud, and shows which kind of saying each arrow rests
on — including a heavy inverted arrow for one whose citation failed, so a
forced page has no element left claiming everything is fine.

Numbers 8 and 9 look like plumbing and are not. This skill is driven by an agent
that navigates with `rules_cli.py` and then writes an answer. A tool that
misleads it yields a wrong conclusion **cited correctly** — every downstream gate
passes, because the verifier checks that a quote is real, not that the reasoning
resting on it is sound. Round 8 found `grep` displaying the exact opposite of a
rule by clipping the sentence before its "not". Nothing downstream could catch
that.

## The smell: would this check pass if the behaviour were deleted?

That is the one question worth asking of every check here, because the routes
into a check-that-cannot-fail keep differing while the smell stays identical.
Four found across two codebases in two days, by four unrelated routes:

| route | what it looked like |
|---|---|
| redundancy | two gates guard one path; remove either and the other still holds |
| shell globbing | `unzip -q dist/*.zip` reads only the FIRST archive and passes |
| a no-op transition | recalling a unit to the base it already occupies changes no state, so "left alone" and "swept and put back" are indistinguishable |
| truthiness | `if not heading` accepts `"   "`, and the check never varied the type |

None of those is findable by looking for the others. What they share is that
the check would have passed with the behaviour it names removed — so ask that,
rather than trying to recognise the shapes.

Two corollaries worth stating, because both cost time here:

- **A fix without a case behind it is not pinned.** Guard fixed, table not
  extended, mutant reverting it survives. The fixed code passes the existing
  check either way, because the check was never watching the property the fix
  established.
- **When a correct no-op and an incorrect no-op leave the same state, the
  check has to read the trace**, not the state.

## Redundant guards are invisible here

A mutation battery changes one site at a time, so a property defended TWICE is
pinned by nothing: remove either guard and the other still holds, the suite
stays green, and the battery reports both as covered.

It is not hypothetical. `cmd_report` refuses a document with problems, and the
renderer it shells out to refuses again — and `cmd_report`'s gate, whose own
docstring calls it *"the ONLY way to finish an answer"*, could be deleted
outright without a single check going red.

The fix is a check per guard, written so it can tell **which one fired**. The
two gates announce themselves differently on purpose (`not rendering` from the
CLI, `refusing to render` from the renderer), so a check can assert that the
near gate caught it and the far one was never reached.

When you add a second guard to something already guarded, add the check that
distinguishes them at the same time. Otherwise you have made the system safer
and the suite blinder, and only the second of those is visible.

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

## "All N checks passed" is half a sentence

The suite prints a second line beside its headline, and that line is the one
that means something:

```
all 350 checks passed — safe to answer against this corpus
  of 295 distinct checks, 197 have been observed to fail (66%).
```

A mutation battery reports how many mutants were caught, which reads like
coverage and is not — it is coverage of the behaviours somebody thought to
attack. A check with no mutant behind it has never been seen to fail and is
therefore indistinguishable, from inside a green run, from one that **cannot**.
The 98 unproven checks here are not evidence of 98 defects; they are the
population a defect would hide in, and nothing in a passing run points at them.

The perverse part is the arithmetic: adding an untested check raises the
headline. The number goes up, the evidence does not, and the suite looks
stronger for having grown weaker per check. So both numbers are printed
together, because the first one alone was quoted all day by two agents who knew
better.

Audited for the shapes that cannot fail — `is not None` against something that
raises, counts compared to zero, truthiness of a value that is always truthy —
the unproven population currently returns **zero** hits on both this skill and
deck-lab. That is worth exactly what it says: clean on the two things we knew
to look for.

## What this is not

It is not a claim that the code is defect-free. Coverage of the whole suite is
about two thirds; the remainder is mostly cosmetic and is listed in
`docs/known-issues.md`. It is a claim that the twelve statements above are the
ones worth blocking a release on, and that each is currently held up by a check
that has been seen to fail.
