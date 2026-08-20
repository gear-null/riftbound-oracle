# Known issues

Everything here was found by review, reproduced, and deliberately not fixed. It
is listed so that shipping is a decision rather than an oversight. None of it
violates an invariant in [`invariants.md`](invariants.md); anything that did
would have blocked the release.

## Accepted, with reasons

**`card` reports "(none printed)" for four cards that print an unbracketed
keyword.** Windsinger (Hidden), Laurent Bladekeeper (Ganking), Disintegrate
(Action), Jagged Cutlass (Equip). Riot does not bracket every keyword and the
extractor is brackets-only. An affirmative false negative, but a narrow one: four
cards of 1,037, and the agent can still reach the rules by section. Fixing it
means promoting a bare glossary term from a keyword-line position, which risks
false positives across the whole pool.

**`keysFor` builds no base alias for comma-subtitled or very short names.**
`card "Gangplank"` fails where `card "Gangplank, Naval"` works, for 17
comma-subtitled and 16 short-base cards. The failure is loud — it says no card
matched — so it cannot fabricate an answer. The recovery hint ("cards are matched
on their base name") is nonetheless wrong for exactly those cards.

**A cost change expressed only inside bracket notation reads as a reprint.**
`sameWording` strips bracket contents because Riot writes `[1][C]` where the API
sends `:rb_energy_1:`, so `[1]` → `[3]` compares equal and the erratum is not
applied. No live instance today; pinned by a test that asserts the limit rather
than hiding it. Closing it means canonicalising both notations instead of
deleting them.

**`RIFTBOUND_RULES_VERSION` can turn the gate red.** Setting it makes the
committed rulebook disagree with the generator, and the failure message advises
committing an artifact stamped with a local override. It is read in one place and
documented nowhere else. Leave it unset.

**The mis-attribution diagnostic ignores Examples.** A quote lifted from an
Example and cited at the wrong rule is called "paraphrased" rather than "it
appears in CR:X". The citation is still correctly refused; only the repair advice
is less useful.

## Coverage

About two thirds of the 205 checks are proven by the mutation battery. The
unproven third is mostly display detail and data-shape assertions. The eleven
invariants are fully pinned, which is the property the release gate enforces.

Two checks are known to be weaker than their names suggest and were kept rather
than deleted, because deleting them would lose the documentation value:
`prose brackets are not treated as symbols` and `a section with children has no
topic block`. Neither can be made to fail by a single-site edit.

## Reporting

If something here bites you, it should become an invariant rather than a patch.
See [`invariants.md`](invariants.md#adding-one).
