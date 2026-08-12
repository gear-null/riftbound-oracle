# How to read a report

Every answer is one HTML file in `.claude/skills/rules-report/reports/`. It is
self-contained, works offline, and can be kept or sent on.

## The verdict line

One sentence, typed. Each part of it carries a **superscript** pointing at the numbered
claim that supports it — `…played this turn⌁5`. Click through and that claim's citations
open. A `⌁` before the number means the step is inferred rather than stated outright.

## Basis: how well a claim is supported

| basis | glyph | means |
|---|---|---|
| `grounded` | ● | a rule states this in so many words |
| `structural` | ▲ | no single rule says it; it follows from the rules cited |
| `gap` | ○ | the rules don't address it |

## Weakest link

The header reads e.g. `weakest link: note 5 (structural)`.

Confidence is **`min()` across claims, never an average**. Nine grounded claims plus one
structural makes a structural answer. A chain is only as strong as its weakest step, so
that is what gets reported rather than a flattering summary.

## Crux and "if this is wrong"

Exactly one claim is marked **CRUX**: the load-bearing one. It must state what happens
if it is wrong, and whether the holding flips. That collapses the job of auditing an
answer from *N* claims to one.

## Citations

Each expands in place to show the cited rule with its **ancestor spine** — a rule is
meaningless without the clause it sits under. Every ID in that spine links into the
full anchored rulebook, which opens in an overlay so you keep your place.

The green **verified** stamp means code checked that the rule exists and that the quoted
span appears verbatim in it. If a citation the holding depends on fails, the disposition
is forced to `UNSETTLED` and the report will not render at all.

## Counterargument

The opposing reading is stated at full strength, by rule, then rejected. A reader who
has already read the contrary rule will not believe the holding until it is confronted.

## Cards referenced

Any card the answer discusses, with artwork, structured stats, its printed text, and
links to the glossary sections its keywords map onto. Artwork is loaded from Riot's CDN
by URL; no image is stored in this project.

## Symbols used here

A key to the bracketed shorthand on that page — `[A]`, `[E]`, `[2]` — each entry linking
to the rule that defines it. The text itself is left as Riot prints it, deliberately:
the legend is there to become unnecessary. See
[ADR 0006](adr/0006-derive-the-symbol-legend.md).

## Dispositions

`YES` · `NO` · `DEPENDS` · `UNSETTLED`.

`UNSETTLED` is a real answer, not a failure. When the rules genuinely don't settle a
question, saying so with the gap named is more useful than a confident answer you
cannot check — and it is the one thing a general-purpose chatbot will not give you.
