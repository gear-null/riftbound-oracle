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

About two thirds of the 260 checks are proven by the mutation battery. The
unproven third is mostly display detail and data-shape assertions. The twelve
invariants are fully pinned, which is the property the release gate enforces.

`scripts/check-invariants.py` prints both numbers, so read them from it rather
than from this paragraph — a hardcoded count in prose is how the README's
version of this went stale in the first place.

Two checks are known to be weaker than their names suggest and were kept rather
than deleted, because deleting them would lose the documentation value:
`prose brackets are not treated as symbols` and `a section with children has no
topic block`. Neither can be made to fail by a single-site edit.

## Reporting

If something here bites you, it should become an invariant rather than a patch.
See [`invariants.md`](invariants.md#adding-one).

## deck-lab

Four fidelity gaps left open after the pre-merge review of #9 fixed the other 50.
Each is a place the table is *less* precise than the rules, never more permissive
in a way that hands out points.

**Victory is decided the moment a point is gained, not at the next cleanup.**
472 places the check at a cleanup, and 323.1 makes it that cleanup's first task;
the table checks immediately. The difference is visible only if something would
have removed the winning point between the gain and the cleanup, which nothing
in the modelled subset does. 431.3.c.1 already requires the immediate form for
burn-out points, so both behaviours exist in the rules and the table implements
one of them everywhere.

**A caller-supplied damage assignment is applied without checking it is legal.**
`resolve_combat(index, attacker_assignment=…)` exists so an effect that modifies
damage — Prevent (437) is the plain case — can be expressed, and 465.2.c's
lethal-first and minimum-lethal constraints are not re-checked against it. The
computed assignment the table produces on its own IS checked, and is what every
ordinary combat uses. Validating an arbitrary override means deciding which of
465.2.c.5-c.9's replacement and priority interactions the override represents,
which is not recoverable from a dict of numbers.

**A non-combat Showdown resolves at the following cleanup rather than as a
window.** A unit alone at a contested battlefield takes control there (466.5),
which is where the point lands either way. What is missing is the window itself:
neither player gets a chance to act between contesting and resolving. The Chain
is not modelled either, so there would be nothing to do in that window — see
[ADR 0007](adr/0007-the-table-not-the-player.md).

**Healing after combat is not staged as a cleanup.** 466.1.a inserts "3c. Heal
all Units" into a Combat Special Cleanup whose step 3b kills lethally damaged
units; the table kills and then heals directly. The order is right and the
outcome matches, but an effect keying off that cleanup would have nothing to key
off.

**A card carried a stray token from extraction, and it cost real work.**
`Gemhand Hunter` arrived from the API as `…get the effect.)ambush` — a bare lowercase word
fused to the closing paren, the only card in the pool shaped that way. It is not a mangled
keyword: all 19 genuine `[Ambush]` entries are bracketed, lead the text and carry the
standard reminder, and this had none of those properties. Two agents nevertheless built and
piloted decks around a keyword the card does not have, and it decided a logged game.
`stripTrailingArtifact` removes it during extraction and REPORTS every removal, because
silently deleting text is its own way of asserting something about a card.

The class is now closed at both ends. `corpus.artifact_complaints()` scans the vendored card
text for the same signature UNANCHORED, and the selftest asserts the pool is clean — 334
checks, three mutants. The two halves are deliberately asymmetric: the stripper deletes, so
it stays anchored and conservative; the detector only reports, so it casts wider on three
axes (unanchored, a larger punctuation class, a floor of two letters rather than three). A
detector derived from the stripper could only find what the stripper already removes, so
neither may be moved toward the other.

What remains genuinely open is narrower than it was: a stray token that happens to spell a
real keyword AND is separated by a space is still invisible to both skills — `card_bridge.py`
maps brackets, deck-lab reads printed text, and the fused-punctuation signature is what
caught this one. Nothing here detects a well-formed lie.
