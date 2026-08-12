<p align="center">
  <img src="riftbound-oracle.png" alt="Riftbound Oracle" width="100%" />
</p>

# Riftbound Oracle

Answer Riftbound TCG rules questions with **citations you can actually check**.

Ask a question, get an interactive HTML report: a one-line verdict, the reasoning broken into
individually-graded claims, and every citation expandable to the real rule text *with its ancestry*.
Before the report is written, a deterministic verifier proves that every cited rule exists and that
every quote appears verbatim. A citation that fails cannot reach you.

It runs entirely on your machine, driven by whatever LLM agent you already use — and it
installs by copying one folder.

---

## Why not just ask an LLM (or NotebookLM)?

Because the citations are the whole problem. A confident answer citing `471.1.b` is worthless if
that rule says something else, or doesn't exist — and both happen constantly. Measured during
development over 7,774 community-written answers to real Riftbound questions: of the 831 that
cite a rule ID, **29% of those citations point at a rule ID that doesn't exist at all.** Not
misread — absent. And that is only the mechanically checkable half; whether a *real* rule says
what the answer claims is a judgement no grep can make.

Riftbound rules have a property that makes something better possible: every atomic claim already has
a canonical address like `471.1.b.1`. So this system cites **rules**, not text fragments, and then
checks them mechanically.

It also refuses. Probed during development with five adversarial traps — a card that doesn't
exist, a real card lacking the behaviour asked about, an invented keyword, a stale rule number,
and a genuine gap in the rules — it produced **zero fabrications**.

---

## Install

Copy the skill into your project. That is the whole install.

```bash
git clone <this repo> /tmp/riftbound-oracle
mkdir -p .claude/skills
cp -R /tmp/riftbound-oracle/.claude/skills/rules-report .claude/skills/
```

**Requires:** Python 3.10+ and an LLM agent that can run shell commands and read files
(Claude Code, or any agent with equivalent tool access). No Node, no build, no network, no API
key. The rulebook, the card data and the anchored HTML rules all ship inside the folder — 2.6MB.

Confirm it works:

```bash
cd .claude/skills/rules-report/lib
python3 rules_cli.py selftest        # regression harness; prints its own count
python3 rules_cli.py card "Astral Heron"
```

`selftest` should end with `all checks passed`. Then just ask your agent a rules question.

> The Node pipeline in `src/` is the **maintainer** side — it regenerates the data the skill
> ships with. You do not need it to use the skill. See [Maintaining](#maintaining) if you want to
> refresh the corpus after a Riot rules update.

---

## Asking a question

Point your agent at [`.claude/skills/rules-report/SKILL.md`](.claude/skills/rules-report/SKILL.md)
and give it a question. In Claude Code the skill is picked up automatically:

```
Does a countered Flow spell still get banished?
```

The agent navigates the rulebook using the tools below, writes a structured answer, verifies it, and
opens the report. **You never run a command yourself** — except `selftest` after a rules update.

### What you get back

Reports land in `.claude/skills/rules-report/reports/` and are self-contained HTML you can open,
keep or send on. Three things in them are worth knowing about:

**Citations are followable.** Every cited rule expands in place to show its ancestor spine, and
every id in that spine links into `data/rules.html` — the full rulebook rendered with an anchor on
all 3,316 rules. Clicking lands on the exact clause, highlighted, in context, with its own
cross-references live. It is a local file, so this works offline and keeps working if you move the
`rules-report` folder somewhere else.

**Cards are shown.** Any card the answer discusses appears with its artwork, printed text, and
links to the glossary sections its keywords map onto. Artwork is loaded from Riot's CDN by URL —
no image is stored in this repo.

**Claims are numbered like footnotes.** The verdict is one sentence, and each part of it carries a
superscript pointing at the numbered claim that supports it — `…played this turn⌁5`. Click through
to claim 5 and its citations open. A `⌁` before the number means that step is inferred rather than
stated outright.

**Confidence is a floor, not an average.** The header reads e.g. `weakest link: note 5
(structural)`. That names the shakiest claim in the chain and how well it is supported —
`grounded` (a rule says it outright), `structural` (it follows from the rules cited), or `gap`
(the rules don't address it). One `structural` step makes the whole answer structural. A chain is
only as strong as its weakest link, so that is what gets reported.

**A key to the shorthand, when it is used.** Rules text is full of bracketed shorthand — `[E]: Add
[Y].` is opaque until you know it means "exhaust this: add one Power of Order". Reports end with a
legend covering exactly the symbols on that page, each linking to the rule that defines it. The
text itself is left as Riot prints it, deliberately: the legend is there to become unnecessary, so
that you end up able to read Riot's own PDFs unaided. The legend is derived from CR 134.2 and
135.2.e rather than hardcoded, so it follows a renumbering on its own.

### The tools your agent uses

Run from `.claude/skills/rules-report/lib/`:

| command | what it does |
|---|---|
| `rules_cli.py card <name>` | Exact card lookup → printed text, keywords, mapped rule sections |
| `rules_cli.py rule <id>` | A rule **with its ancestor spine**, children, examples, cross-refs |
| `rules_cli.py section <id>` | A whole numbered section in document order |
| `rules_cli.py grep <query>` | Lexical search (SQLite FTS5 syntax) |
| `rules_cli.py report <json>` | **Verify + render + open.** How an answer is finished |
| `rules_cli.py rulebook` | Regenerate the anchored HTML rulebook |
| `rules_cli.py selftest` | Regression harness |

The division of labour is the design: **the agent decides what to look at; code decides whether the
citations are real.**

---

## Using a different LLM

Nothing here is Claude-specific. `SKILL.md` is plain markdown describing a procedure, and the tools
are ordinary CLI programs. To use another agent, give it `SKILL.md` as instructions and shell access
to `lib/`. The parts that must not be improvised — does this rule exist, does it say this verbatim,
which rule is the tightest one that says it — are enforced by `rules_cli.py verify`, not by the
model's good intentions.

If your agent produces an answer whose citations fail verification, `report` refuses to render it.
That is the intended behaviour.

---

## How it works

Four layers. Only two involve a model.

1. **Corpus** — 3,300+ rules parsed into a tree with parent, children, examples, cross-references,
   pinned to a rules version. *Deterministic.*
2. **Navigate** — the agent resolves named cards exactly, then walks the rulebook until it can state
   the governing rule. *Agent.*
3. **Answer** — a structured holding: one typed line, claims graded `grounded` / `structural` /
   `gap`, one crux with a stated counterfactual, and the opposing reading confronted by name.
   *Agent.*
4. **Verify** — every citation must exist, quote verbatim, and be narrowed to the tightest rule whose
   own text says it. A failure forces the verdict to `UNSETTLED`. *Deterministic.*
5. **Link** — the report and the anchored rulebook are generated from the same parsed corpus the
   verifier checks against, so a citation and its link can never disagree. *Deterministic.*

**Retrieval was built first, then rejected.** Lexical search over the rules reached 32% recall@10
on a 620-question benchmark — measured during development, against a corpus this repo no longer
ships, so treat that number as history rather than something you can re-run.

The *reason* is checkable, and it's the durable part: card names essentially never appear in rule
text. Grep the shipped corpus for any card you like. Users ask in **card** vocabulary ("does
Windsinger…"); the rules are written in **rules** vocabulary. Searching a rulebook for a card name
finds nothing, and the gap runs one way — so cards are looked up exactly, and rules are navigated.

---

## Maintaining

Only needed when Riot ships a rules update or a new set — and only by whoever maintains the
skill's data. Users just take the newer folder.

This is the one place the Node pipeline is required:

```bash
npm install && npm run build

npm run oracle process -- --only=rules   # refetch the Rules Hub
npm run oracle extract                   # rulebook PDFs -> markdown
npm run oracle skill-data                # rebuild data/cards.json

cd .claude/skills/rules-report/lib
python3 rules_cli.py build               # re-parse -> data/rules.json
python3 rules_cli.py rulebook            # re-render -> data/rules.html
python3 rules_cli.py selftest            # regression harness
```

`data/rules.json` is committed on purpose: a rules update then arrives as a **reviewable diff of
rule IDs** rather than as a wrong citation discovered months later. The 2026-07-16 update
renumbered much of the 400s (Movement 440→445, Scoring 462-467→467-472), exactly the kind of
change that silently invalidates saved answers — and now also silently breaks anchor links, which
`selftest` checks for.

> **Rate limiting.** Riot's Rules Hub sits behind Cloudflare and will reset connections if hit
> repeatedly. Run rules updates on demand, never on a schedule. On `ECONNRESET`, wait or change
> network — don't retry into it.

---

## Sources and their authority

**Riot's own documents are the only thing this cites** — Core Rules, Tournament Rules, patch notes
and errata, plus Riftcodex card data. There is no second tier: no community Q&A, no FAQ scrape, no
forum archive.

That's a deliberate choice, not an omission. When the rules genuinely don't settle a question, the
answer is `UNSETTLED` with the gap named. An unsettled question honestly labelled is more useful
than a confident answer you can't check — and it's the one thing a general-purpose chatbot won't
give you.

A 7,774-answer community corpus was crawled and evaluated for a second tier, then dropped: 0.06%
of its answers mentioned Riot, 0.2% flagged a coming rules change, and 0.05% admitted the rules
didn't settle the question. It never did the job that would justify the risk, while answering
confidently regardless. It also produced a concrete error — a "take control" exception to
banishment that `829.1.b` flatly contradicts.

---

## Content and licensing

Riftbound is a trademark of Riot Games. This project is **unofficial and not endorsed by Riot**.

**What this repo contains:**

| | |
|---|---|
| Rules text (Core, Tournament, patch notes, errata) | committed — needed for verifiable citation |
| Card text (names, stats, abilities) | committed |
| **Card artwork** | **never committed** |
| **Community Q&A** | **never committed, and no longer crawled** |

**Card artwork is not redistributed.** No image file is tracked here. When you run
`oracle card-index`, it writes `output/card-index.json` — a list of URLs pointing at Riot's own CDN —
and that file is gitignored, so each user generates their own. Reports reference artwork by URL; the
images are served by Riot and never copied into this repo. Without the index, reports render a
placeholder and everything else works normally.

**No community content is redistributed, and none is fetched.** The crawler that built the corpus
described above has been removed along with every artifact derived from it, so nothing here quotes
or scrapes anyone's community work.

The rules and card *text* are committed deliberately: the whole point of this tool is verifying
quotes verbatim against a pinned corpus, which is impossible if the corpus isn't there. If you fork
this and would rather not redistribute it, delete `output/` and the committed `rules.json` — the
commands above rebuild everything from source in a few minutes.

---

## Layout

```
.claude/skills/rules-report/   <- THE PRODUCT. Copy this folder; nothing else is needed.
  SKILL.md                     the procedure your agent follows
  lib/                         rules_cli.py and the deterministic tools
  data/                        vendored + committed, 2.6MB
    rules.json                 3,316 parsed, addressable rules
    cards.json                 card text + artwork URLs
    rules.html                 anchored rulebook that citations link into
  reports/                     generated HTML reports (gitignored)

                               --- maintainer side, not needed to use the skill ---
src/                     TypeScript pipeline (fetch, parse, normalise)
  processors/            one per source type: riftcodex, rules-hub, pdf, html, url
  skill-data.ts          builds data/cards.json
manifests/sources.yaml   prescriptive: what gets fetched and where it lands
output/                  intermediate corpus the skill data is built from
scripts/pdf-extract.py   pdfplumber PDF → text
```
