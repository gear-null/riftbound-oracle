---
name: rules-report
description: Answer a Riftbound rules question as a verified, citation-checked interactive HTML report — either a RULING that settles a disputed situation ("does X still happen if Y", "can I respond to Z", deck/sideboard legality, how much does this cost) or a PRIMER that explains how a mechanic or procedure works ("explain the HOT FEPR loop", "how do Showdowns work", "walk me through combat"). Use whenever the user asks about a Riftbound rule, card interaction, keyword, turn structure, or tournament procedure. Also use when asked to re-verify a saved report after a rules update.
---

# Riftbound rules report

Answer a rules question by **navigating the official rules yourself** and emitting a
structured answer whose every citation is then mechanically verified.

You are the reasoning step. The tools below are deterministic and exist so that the
parts which must not be improvised — does this rule exist, does it say this verbatim,
which rule is the tightest one that says it — are not left to judgement.

## Two documents. Pick one first.

| | **Ruling** | **Primer** |
|---|---|---|
| answers | a *situation* | a *mechanic* |
| the ask | "does X still happen if Y", "can I respond", "how much", "who chooses" | "explain X", "how does X work", "walk me through X" |
| shape | one holding line, typed into spans, one crux, the opposing reading confronted | numbered steps, each with the transitions out of it, plus a derived diagram |
| file | `answer.json`, no `kind` field | `primer.json`, `"kind": "primer"` |

**The test:** could someone put this to a judge at a table and get a yes, a no, or
a number? Then it is a ruling. Is it a topic rather than a moment — something you
would want *before* the game rather than during it? Then it is a primer.

Do not write a ruling for a question that has no proposition to defend. Ask for the
HOT FEPR loop and the honest answer is five steps and twelve transitions between
them, four of which send you backwards; forcing that into a holding line and a
single crux produces a worse document and an arbitrary choice of which step is
"load-bearing". Equally, do not write a primer to duck a question that *does* have
an answer — a primer that explains the machinery around a question the user actually
asked is an evasion, not an explanation.

**Both are held to the same standard of proof.** Same verbatim gate, same basis
vocabulary, same `min()` confidence, same refusal to render on a failed citation.
The primer is stricter in exactly one place, and it is the important one: see
*A transition is a claim* below.

## Why it works this way

Lexical (BM25) retrieval over the rules was built, measured, and rejected: **recall@10
was 32%** across 620 real questions. The cause is a one-way vocabulary gap — **65% of real
questions name a card, and only ~4% of card names appear anywhere in rule text.** So:

- **Cards** are looked up **exactly**, by name. This direction works perfectly.
- **Rules** are **navigated**, not retrieved. Read the section, walk the ancestry.

Never answer a rules question from memory. Rule numbers were renumbered in the
2026-07-16 update (Movement 440→445, Scoring 462-467→467-472); anything you recall may
name a rule that has since moved.

## Before you start

**Requires Python 3.9+**, which includes the interpreter stock macOS ships. No
third-party packages.

Everything the tools need ships inside this folder. You never need to run
`build` — that is a maintainer command needing source material a normal install
does not have.

## Tools

Run from `lib/`: `python3 rules_cli.py <cmd>`

| command | what it does |
|---|---|
| `card <name>` | Exact card lookup → printed text, its `[Keywords]`, and the rule sections those map to |
| `rule <id>...` | A rule **with its ancestor spine, children, examples and cross-refs**. `829.1.b.1` or `TR:601.1.c.1` |
| `section <id>` | A whole numbered section in document order. A bare heading also prints the sibling sections holding its rules |
| `grep <fts query>` [`-n N`] | Lexical search over rule text. SQLite FTS5 syntax: `"burn" NOT "burn out"`, `banish*`, `sideboard AND size`. Capped at 12; raise it with `-n 50` |
| `selftest` | Regression harness; run after every rules update |
| `report <answer.json>` | **How you finish.** Verify + render + open, in one step |
| `verify <answer.json>` | The citation gate alone. Exit 1 if anything fails |
| `render <answer.json> [out]` | Render alone; prefer `report` |
| `graph <primer.json> [out.mmd]` | A primer's step graph as Mermaid source, derived from its verified transitions |

`card`, `rule`, `section` and `grep` are how you research either document. `report`,
`verify`, `render` and `graph` read the file's `kind` and route themselves — you never
name the document type on the command line.

## Procedure — a ruling

1. **Reframe.** Restate the question in *rules* vocabulary. Card and slang terms
   ("defy", "rebuttal", "fizzle", "stack") mostly do not appear in the rules — translate
   them. Keep the reframe; it goes in the report.

2. **Resolve every card named.** `rules_cli.py card "<name>"` for each. The printed text
   and its keyword→rule links are your entry point into the rulebook. If a card is not
   found, say so rather than guessing at its text.

3. **Navigate the rules.** From the card's keywords, `rule` into those sections and read
   them properly — ancestors included. Follow `see also` cross-references. Use `grep` to
   find terms you don't have an entry point for. Confusable actions are **distinct
   sections** and must not be conflated: 416 Recycle · 427 Banish · 431 Burn Out ·
   440 Burn · 441 Empower · 442 Disempower · 443 Skip.
   Keep going until you can state the governing rule; do not stop at the first plausible hit.

4. **Find the counterargument.** Actively look for the rule that appears to say the
   opposite. A reader who has read it will not believe you until you confront it by name.
   If you cannot defeat it on the text, the disposition is `DEPENDS` or `UNSETTLED`.

   **Do not force a yes/no.** Most rules questions are not yes/no questions —
   "how much?", "what happens?", "in what order?", "who chooses?". For those the
   disposition is `ANSWER` and the holding line *is* the answer; the report leads
   with it and shows no verdict word. Reserve `YES` and `NO` for questions that
   genuinely have one, which is what keeps them worth reading at a glance.

5. **Write `answer.json`** (schema below). Quote **verbatim** — copy from tool output,
   never retype from memory. Cite the **tightest** rule that actually says the thing.

6. **Finish with `report`.** `rules_cli.py report answer.json` — this verifies, renders
   and opens the report in one step. **An answer is not delivered until this has run.**

   Never leave the user with an `answer.json` and an instruction to run something
   themselves. If verification fails, `report` refuses to render and tells you where the
   quote actually lives — fix the citation and re-run. Never hand-wave a failure; if a
   claim cannot be grounded, downgrade its basis to `structural` or make it a `gap`.

7. **Report back in the chat**: the disposition, the weakest link, anything unresolved,
   and the path to the HTML. The reasoning belongs in the report; the chat message is the
   summary plus the link, not a second copy of the argument.

## answer.json

```json
{
  "question": "verbatim as asked",
  "reframe": "the same question in rules vocabulary (the report prefixes \"As the rules see it:\" — do not repeat it)",
  "corpus": {"CR": "2026-07-16", "TR": "2026-07-16", "generated": "YYYY-MM-DD"},
  "holding": {
    "disposition": "YES | NO | DEPENDS | UNSETTLED | ANSWER",
    "line": "one sentence",
    "spans": [{"text": "exact substring of line", "basis": "grounded|inferred", "note": "n1"}]
  },
  "notes": [{
    "id": "n1",
    "claim": "one checkable claim",
    "basis": "grounded | structural | gap",
    "detail": "optional",
    "crux": true,
    "if_false": "required when crux — what breaks, and does the holding flip?",
    "rules_checked": ["829", "390"],
    "cites": [{"rule": "CR:829.1.b.1", "quote": "verbatim span"}]
  }],
  "counterargument": [{"reading": "opposing reading at full strength",
                       "why_it_loses": "...", "cites": [...]}],
  "considered_rejected": [{"rule": "CR:370.3", "why": "one line"}],
  "open_questions": ["..."],
  "cards": ["Astral Heron"]
}
```

**If the reader has no browser** — a desktop or mobile app rather than a terminal — set
`RIFTBOUND_EMBED_ART=1` before `report`. Preview panes block remote images, so the card
artwork would otherwise show "artwork offline". Embedding inlines it, making the report
self-contained at roughly 1MB per card.

**`cards` is a list of names, nothing more.** Name every card the question or
your answer discusses, spelled as `rules_cli.py card` resolved it. The renderer
looks each one up in the skill's card data and renders its artwork, printed
text and governing rule sections. Do not supply text or image URLs yourself —
those are exactly the fields you would get subtly wrong, and the lookup is
already exact. A name that does not resolve is shown as "not found" rather than
dropped, so a typo is visible instead of silent.

Rules the renderer enforces, so write to them:

- Every `spans[].text` must be an **exact substring** of `holding.line`.
- Exactly **one** note is `crux: true`, and it must have `if_false`.
- A `gap` note must list `rules_checked` — abstention is audited to the same standard
  as assertion.
- Confidence is **min()** over notes, not an average. One `structural` note makes the
  whole answer structural, and the report says so.
- If any citation fails verification the disposition is **forced to UNSETTLED**. You
  cannot outrun the verifier — fix the citation instead.

## Procedure — a primer

Steps 1–3 are the same: reframe, resolve every card named, navigate the rules. Read
the *whole* topic before writing anything — a primer that stops at the first section
describes half a procedure, which is worse than describing none.

4. **Lay out the steps.** One step per thing that actually happens, in the order the
   rules put them in. Use the rules' own names for them (`337. Step 1: Finalize`
   becomes `F — Finalize`), because a reader who learns your names cannot then read
   Riot's document.

5. **Write the transitions out of each step.** For every step, answer: *what sends
   you somewhere else, and where?* One `exits` entry per condition, each naming the
   step it leads to — or omitting `goto` entirely, which is how you say the procedure
   ends there.

   **A transition is a claim.** `exits[]` is not decoration for the diagram; it is
   the assertion "the rules send you from here to there when this holds", and it is
   the part a reader will act on at the table. Its default basis is `grounded`, so an
   uncited transition **fails verification** — it is not rendered as confident prose
   the way an uncited sentence in a paragraph would be. If a move genuinely follows
   from the rules rather than being written in one place, declare
   `"basis": "structural"` and it may go uncited — but the whole document's
   confidence then drops to structural, and the diagram draws that arrow dashed.

6. **Do not draw the diagram.** There is no field for it. The map is derived from
   `steps` and `exits` by `flowgraph.py`, so it cannot show an arrow you did not cite
   — which is the only reason a picture is publishable here at all. If the map looks
   wrong, the transitions are wrong; fix those.

7. **Find what people get wrong.** `misconceptions` is the primer's counterargument:
   the belief stated at full strength, then the rule that refutes it. A primer with
   none is usually a primer that has not been read against how the mechanic is
   actually played.

8. **Finish with `report`**, exactly as a ruling does. It routes on `kind`, verifies,
   renders and opens. **A primer is not delivered until this has run.**

## primer.json

```json
{
  "kind": "primer",
  "topic": "HOT FEPR",
  "question": "verbatim as asked",
  "reframe": "the same question in rules vocabulary",
  "corpus": {"CR": "2026-07-16", "TR": "2026-07-16", "generated": "YYYY-MM-DD"},
  "in_one_line": "what the whole thing does, in one sentence — no verdict word",
  "steps": [{
    "id": "s1",
    "heading": "H — Handle Outstanding Tasks",
    "body": "prose, as long as it needs to be",
    "basis": "grounded | structural | gap",
    "rules_checked": ["332", "333"],
    "cites": [{"rule": "CR:334", "quote": "verbatim span"}],
    "exits": [{
      "when": "the condition that sends you there",
      "goto": "s2",
      "basis": "grounded (default) | structural | gap",
      "cites": [{"rule": "CR:336", "quote": "verbatim span"}]
    }]
  }],
  "misconceptions": [{"belief": "stated at full strength",
                      "why_wrong": "...", "cites": [...]}],
  "considered_rejected": [{"rule": "CR:305", "why": "one line"}],
  "open_questions": ["..."],
  "cards": ["Astral Heron"]
}
```

Rules the renderer enforces, so write to them:

- A transition with **no `cites`** and no declared basis **fails**. Grounded is the
  default and grounded means a rule says it.
- Every `goto` must name a step in this primer. There is no cross-document jump.
- Once *any* step declares an exit, the document is claiming to describe a procedure:
  every step but the first must be reachable, and **one transition must omit `goto`**
  so the procedure has a way out. A primer with no exits at all is a linear
  explainer — "the parts of a card" — and none of this applies to it.
- A `gap` step or transition must list `rules_checked`.
- Confidence is **min()** over steps **and transitions**. A document whose steps are
  all grounded but whose transitions are guesses is a guess about the procedure,
  which is the only thing anyone reads a procedure primer for.
- **A step's `body` must stay inside what that step cites.** The basis chip is a
  claim about the whole step — `grounded` reads as *a rule states this in so many
  words* — so a synthesis across neighbouring steps does not belong in the prose of
  a grounded one. Either ground it, or say it in a step you have marked
  `structural`. This is the one place fluency will cost you: the sentence that
  reads best is often the one drawing on three rules the step never cited.
- **`in_one_line` is not separately graded.** It is a summary of the steps, so it
  must not say anything they do not. Unlike a ruling's holding line it carries no
  typed spans, which makes it the one sentence you have to keep honest yourself.
- Step ids are the page's anchors, so they must be unique.
- There is **no disposition and no crux**. A primer states no verdict; if you find
  yourself wanting one, you are writing a ruling.
- If any citation fails verification the primer **does not render at all**. There is
  no UNSETTLED to fall back to.

Once it renders, `rules_cli.py graph <primer.json>` emits the same graph as Mermaid
source for the website and for diagramming tools. It refuses on an unverified primer,
so a diagram can never travel further than its citations.

## Two ways to wrongly conclude the rules are silent

Both look identical to a careless reader: an empty result. Neither is silence.

**A heading's rules can be its siblings, not its children.** Riot writes some topics as
`467. Scoring` followed by sections 468-472 — so 467 has an empty subtree even though five
sections of rules sit directly under it, and `194.1.a` cheerfully says "see rule 467. Scoring".
`section` prints the sibling block for you, but if you reach such a heading another way, keep
reading forward instead of concluding nothing is there.

**`grep` is capped at 12 hits.** It tells you when it truncated. It ranks by lexical overlap, so
it is a way to *locate* rules, never evidence that a rule does not exist. Before writing a `gap`
note, navigate by section number — the rules use vocabulary players do not.

## Distinguish "the rules are silent" from "our data is incomplete"

These are different findings and must not be reported as the same thing.

Some cards' printed text is **incomplete upstream**, and `card` tells you when: it prints
`!!! PRINTED TEXT INCOMPLETE` and says what is missing. Equipment gear is the known case —
the effect it grants once attached is printed in a band at the foot of the card, and reaches
neither the API's text fields nor its attributes. Re-ingesting does not fix it; the gap is in
the source data, not the pipeline.

**Never conclude a card lacks an ability you cannot see in a flagged card's text.** Say the
data is short and scope the answer to what you can verify.

So when a card's printed text does not contain the behaviour asked about, say **which** of these is
true:

- *"The rules do not settle this"* — a genuine gap; use a `gap` note with `rules_checked`.
- *"Our card data does not contain this behaviour"* — a data gap. Still UNSETTLED, but say plainly
  that the card may do this in reality and our copy is short. Answer the rules half if you can
  ("whatever the card does, damage is healed at end of turn per 143.3.b.1") and scope it explicitly.

Never silently convert a data gap into a rules gap. The user can go read the physical card; they
cannot go read a rule that does not exist.

## There is no second-tier source

**Riot's own documents are the only citable material here.** There is no community corpus, no
FAQ scrape, no forum archive — nothing to fall back on and nothing to go looking for. If a
search turns up no rule, that is the finding.

So when the rules are silent, say so. `UNSETTLED` with the gap named is a correct answer; a
confident answer sourced from recollection is not. This is the one place the temptation is
strongest, because silence feels like failure — it isn't.

Do not import an interaction you remember reading about somewhere. A community corpus was
evaluated for this role and dropped: it asserted a "take control" exception to banishment that
`829.1.b` flatly contradicts, and repeating that would have been worse than saying nothing.
