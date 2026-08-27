# How to read a report

Every answer is one HTML file in `.claude/skills/rules-report/reports/`. It carries
its own CSS and JavaScript, so it can be kept or sent on with nothing else attached.

One qualification, because it matters if you print at a venue: **card artwork is the
only thing not in the file.** Reports reference Riot's CDN by URL rather than
redistributing the images, so a reader with no network gets a labelled "artwork
offline" placeholder and everything else — the argument, the citations, the
rulebook links — works normally. Setting `RIFTBOUND_EMBED_ART=1` inlines the art
and makes the file genuinely self-contained, at roughly 1MB per card.

## The rail

On a wide screen the argument sits beside a sticky index: the disposition, the weakest
link, and every claim in order with the **crux** marked. The claim you are currently
reading is highlighted as you scroll, so "which step am I in" never costs you a scroll
back up. At or below 1060px the rail is dropped — the document is already linear — and it is
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

**`gap` notes count.** A gap is the weakest thing a claim can be, so an answer carrying
one reports `gap` as its weakest link even if every other claim is grounded. Earlier the
code excluded them and this page said so; the code, this page and `SKILL.md` disagreed
three ways, and the exclusion was the wrong resolution — it let the verdict plate headline
a grounded weakest link directly beside a `○ gap` row, under the words "the lowest link".

## Crux and "if this is wrong"

Exactly one claim is marked **CRUX**: the load-bearing one. It must state what happens
if it is wrong, and whether the holding flips. That collapses the job of auditing an
answer from *N* claims to one.

## Citations

Each expands in place to show the cited rule with its **ancestor spine** — a rule is
meaningless without the clause it sits under. Every ID in that spine links into the
full anchored rulebook, which opens in an overlay so you keep your place.

The `✓ VERIFIED` stamp means code checked that the rule exists and that the quoted span
appears verbatim in it. A failure inverts to a solid `✗ UNVERIFIED` plate rather than
merely changing hue, so it survives a glance, a greyscale printer and a reader who does
not know the palette.

**Any** failed citation forces the disposition to `UNSETTLED` — in a note or in the
counterargument, load-bearing or not — and `report` then refuses to write the file. The
one way to see such a page is `render --force`, which writes it anyway with the verdict
pinned to `UNSETTLED` and the forced-verdict banner explaining why. That escape hatch
exists for debugging a citation, not for publishing around one.

## Counterargument

The opposing reading is stated at full strength, by rule, then rejected. A reader who
has already read the contrary rule will not believe the holding until it is confronted.

## Cards referenced

Any card the answer discusses, with artwork, structured stats, its printed text, and
links to the glossary sections its keywords map onto. Artwork is loaded from Riot's CDN
by URL; no image is stored in this project, and a reader with no network sees a labelled
"artwork offline" placeholder rather than a broken image.

Setting `RIFTBOUND_EMBED_ART=1` inlines the artwork as `data:` URIs instead, at roughly
1MB per card. That is for readers whose viewer blocks remote images — Claude Desktop's
preview, artifact panes — and it is the one case where this project does hold image bytes,
in the generated report rather than in the repository.

## Symbols used here

A key to the bracketed shorthand on that page — `[A]`, `[E]`, `[2]` — each entry linking
to the rule that defines it. The text itself is left as Riot prints it, deliberately:
the legend is there to become unnecessary. See
[ADR 0006](adr/0006-derive-the-symbol-legend.md).

## Printing

Judges print these. The screen report is dark by design — it follows the Runeterra
visual language, blue-black ground and aged-gold hairlines — but printing inverts the
whole system to a light sheet: dark ink, Gold 700 hairlines (Gold 500 is only 2.2:1 on
white), every `<details>` forced open so no evidence hides — and their prior state
restored afterwards — with the rail, the grain, both buttons, the skip link and the
"Unofficial rules companion" badge all dropped. The footer disclaimer stays. `UNSETTLED`, the forced-verdict banner and a failed citation print
as ruled boxes rather than as fills.

## Dispositions

`YES` · `NO` · `DEPENDS` · `UNSETTLED` · `ANSWER`.

Most rules questions are not yes/no questions. "How much energy does this cost?"
has no one-word verdict, and an early version of this skill answered exactly that
question with **YES** — because the schema offered nothing else. `ANSWER` is that
case: the report prints no verdict word and leads with the holding sentence
instead, which is the answer.

That is also what keeps the other four worth reading. A word set in Beaufort at
the top of the page should mean something, and it only does if it appears where a
one-word answer is real.

`UNSETTLED` is a real answer, not a failure. When the rules genuinely don't settle a
question, saying so with the gap named is more useful than a confident answer you
cannot check — and it is the one thing a general-purpose chatbot will not give you.
