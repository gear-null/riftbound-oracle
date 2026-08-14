# How to read a report

Every answer is one HTML file in `.claude/skills/rules-report/reports/`. It is
self-contained, works offline, and can be kept or sent on.

## The rail

On a wide screen the argument sits beside a sticky index: the disposition, the weakest
link, and every claim in order with the **crux** marked. The claim you are currently
reading is highlighted as you scroll, so "which step am I in" never costs you a scroll
back up. Below 1060px the rail is dropped — the document is already linear — and it is
never printed.

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

The report prints this key once, under the verdict, covering only the bases that answer
actually uses. Each claim then carries the glyph and the word as a chip, so the basis is
never carried by colour alone.

## Weakest link

The verdict plate carries it as a metric — **Weakest link**, the note it points at,
and that note's basis — and the rail repeats it.

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

The `✓ VERIFIED` stamp means code checked that the rule exists and that the quoted span
appears verbatim in it. A failure inverts to a solid `✕ UNVERIFIED` plate rather than
merely changing hue, so it survives a glance, a greyscale printer and a reader who does
not know the palette. If a citation the holding depends on fails, the disposition is
forced to `UNSETTLED` and the report will not render at all.

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

## Printing

Judges print these. The screen report is dark by design — it follows the Runeterra
visual language, blue-black ground and aged-gold hairlines — but printing inverts the
whole system to a light sheet: dark ink, Gold 700 hairlines (Gold 500 is only 2.2:1 on
white), every `<details>` forced open so no evidence hides, and the rail, the grain and
both buttons dropped. `UNSETTLED`, the forced-verdict banner and a failed citation print
as ruled boxes rather than as fills.

## Dispositions

`YES` · `NO` · `DEPENDS` · `UNSETTLED`.

`UNSETTLED` is a real answer, not a failure. When the rules genuinely don't settle a
question, saying so with the gap named is more useful than a confident answer you
cannot check — and it is the one thing a general-purpose chatbot will not give you.
