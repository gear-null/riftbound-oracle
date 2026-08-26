# ADR 0007 — Two document kinds, one verification core

**Status:** accepted · 2026-08-26

## Context

The skill produced exactly one document: a **ruling**. Its shape is not decoration —
every part of it exists to make one contested proposition defensible.

- one holding line, decomposed into typed spans that must be exact substrings of it
- exactly one `crux: true`, which must state what breaks if it is wrong
- `counterargument` — the opposing reading stated at full strength, then rejected
- `min()` confidence over the notes, reported as the weakest link
- a disposition plate: `YES · NO · DEPENDS · UNSETTLED · ANSWER`

That is the right machinery for *"does a countered Flow spell still get banished"*.
It is the wrong machinery for *"explain the HOT FEPR loop"*.

HOT FEPR is CR 332–340. It is five steps with twelve transitions between them, four
of which send play backwards (`337.3`, `338.1.a.7`, `339.2`, `340.3`, `340.4`). Asked
to answer that as a ruling, an author must:

- compress a state machine into one sentence, which the 30%-span-coverage check then
  correctly complains is under-decomposed
- pick one of five equally load-bearing steps as the crux, arbitrarily
- write `if_false` for a claim that nothing flips on
- leave `counterargument` empty, because nobody argues the opposite of a phase order

`ANSWER` — added in 1.2.1 for *"how much does this cost"* — fixes only the verdict
word. Everything below the plate still fights the document.

## Decision

**Add a second document kind, `primer`, sharing the verification core unchanged.**
`kind` is absent for a ruling, so every answer written before primers existed keeps
verifying and rendering byte-for-byte. An unrecognised value is refused rather than
defaulted, because defaulting routes a typo down the ruling path where every
primer-shaped key is simply unread.

Two rejected alternatives:

**Relax the ruling schema so `ANSWER` permits N cruxes and no counterargument.**
Rejected: it makes the ruling's guarantees conditional on its disposition, so a reader
can no longer trust the plate at a glance — which is the exact failure `ANSWER` was
introduced to fix. Two documents with two clear contracts beats one document with a
mode switch.

**Generalise the ruling into a superset both kinds specialise.** Rejected: the ruling's
constraints *are* its value. Loosening them to accommodate a second shape weakens every
ruling to buy a feature neither needs.

### A transition is a claim

The obvious primer is prose paragraphs with citations sprinkled in. That is the format's
whole risk, and it is worse than the ruling's: a model writes eighty percent verified
sentences and twenty percent confident invention, and nobody audits the invention because
the paragraph around it is cited. Fluency is the adversary here in a way it is not when
the output is one defended sentence.

The corpus itself supplied the fix. A procedure is a graph, so the primer's steps carry
`exits[]`, and **an exit is an assertion**: *the rules send you from here to there when
this holds*. Its default basis is `grounded`, so an uncited transition **fails
verification** rather than rendering as prose. Declaring `structural` is permitted and
honest, and costs what it should — the document's `min()` confidence drops, and the
diagram draws that arrow dashed.

This is the primer's equivalent of the ruling's typed holding spans: the part a reader
most relies on is the part code refuses to take on trust. It also makes the primer
*stricter* than a ruling in that one place, which is the answer to "isn't prose the
soft path". An exit is what someone acts on at a table; it may not be asserted more
cheaply than a sentence in a ruling.

### The diagram is derived, never authored

There is no field in which an author can draw an edge. `flowgraph.py` computes the map
from `steps` and `exits` and from nothing else, so every arrow drawn is a cited
transition and every cited transition is drawn — numbered to match the prose beneath it.

This is the same argument as [ADR 0006](0006-derive-the-symbol-legend.md) for the symbol
legend, and it matters more here. A diagram is the surface a reader trusts most and
audits least: an arrow is absorbed at a glance and never checked the way a sentence is.
A hand-drawn diagram beside a verified document is a second, unverified account of the
same procedure, and the moment the rules move, it is the half that goes quietly wrong.

Recorded as **invariant 12** — *a diagram draws exactly the transitions the document
cites, no more and no fewer* — pinned by nine checks, each proven by a mutant.

`rules_cli.py graph` emits the same graph as Mermaid source and refuses on an unverified
primer, so a diagram handed to a website or a restyling pass can never travel further
than its citations.

## Consequences

- Two verify/render paths, one shared set of checks. The blocks both kinds need —
  corpus stamp, `considered_rejected`, `rules_checked`, card `rule_sections`, unique
  ids, required keys — moved out of `verify_answer` into named helpers rather than
  being copied, which is how three citation-tally comprehensions once drifted apart.
- A failed citation means a primer does not render **at all**. A ruling downgrades to
  `UNSETTLED` and says so on the page; a primer has no verdict to downgrade, so the
  only honest response is to publish nothing. `--force` still writes a marked page.
- Shape checks that only apply once a document claims to be a procedure: a step
  nothing reaches, or a loop with no way out, are wrong descriptions rather than
  stylistic choices, and both would be visible on the map. A primer with no exits at
  all is a linear explainer and is exempt.
- The skill's `description` had to widen. It was written entirely in ruling-dispute
  vocabulary, so *"explain the HOT FEPR loop"* would not have fired it.
- `flowgraph.py` also lays the graph out, which is layout code in a project that had
  none. It is bounded on purpose: a vertical spine with off-spine transitions routed
  through numbered gutter lanes, which is the shape every procedure in these rules
  actually has.
