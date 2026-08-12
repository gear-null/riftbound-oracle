# Riftbound Oracle

Answer Riftbound TCG rules questions with **citations you can actually check**.

Ask a question, get an interactive HTML report: a one-line verdict, the reasoning broken into
individually-graded claims, and every citation expandable to the real rule text *with its ancestry*.
Before the report is written, a deterministic verifier proves that every cited rule exists and that
every quote appears verbatim. A citation that fails cannot reach you.

It runs entirely on your machine, driven by whatever LLM agent you already use.

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

## Setup

**Requires:** Node 22+, Python 3.10+, and an LLM agent that can run shell commands and read files
(Claude Code, or any agent with equivalent tool access).

```bash
git clone <this repo> && cd riftbound-oracle
npm install
python3 -m venv .venv && ./.venv/bin/pip install -r requirements.txt

cp .env.example .env          # defaults are fine; nothing secret is needed

npm run build
npm run oracle process        # fetch cards + rules  (network)
npm run oracle extract        # rulebook PDFs -> markdown  (local)
npm run oracle card-index     # optional: card artwork URLs for reports  (network)
```

That fills `output/` with the corpus. Then build the rules index:

```bash
cd .claude/skills/rules-report/lib
python3 rules_cli.py build      # parse the rules into an addressable tree
python3 rules_cli.py selftest   # 26 checks — run this after every rules update
```

`selftest` should end with `all checks passed`. If it doesn't, the corpus changed shape and answers
built on it are not trustworthy yet.

---

## Asking a question

Point your agent at [`.claude/skills/rules-report/SKILL.md`](.claude/skills/rules-report/SKILL.md)
and give it a question. In Claude Code the skill is picked up automatically:

```
Does a countered Flow spell still get banished?
```

The agent navigates the rulebook using the tools below, writes a structured answer, verifies it, and
opens the report. **You never run a command yourself** — except `selftest` after a rules update.

### The tools your agent uses

Run from `.claude/skills/rules-report/lib/`:

| command | what it does |
|---|---|
| `rules_cli.py card <name>` | Exact card lookup → printed text, keywords, mapped rule sections |
| `rules_cli.py rule <id>` | A rule **with its ancestor spine**, children, examples, cross-refs |
| `rules_cli.py section <id>` | A whole numbered section in document order |
| `rules_cli.py grep <query>` | Lexical search (SQLite FTS5 syntax) |
| `rules_cli.py report <json>` | **Verify + render + open.** How an answer is finished |
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

**Retrieval was built first, then rejected.** Lexical search over the rules reached 32% recall@10
on a 620-question benchmark — measured during development, against a corpus this repo no longer
ships, so treat that number as history rather than something you can re-run.

The *reason* is checkable, and it's the durable part: card names essentially never appear in rule
text. Grep the shipped corpus for any card you like. Users ask in **card** vocabulary ("does
Windsinger…"); the rules are written in **rules** vocabulary. Searching a rulebook for a card name
finds nothing, and the gap runs one way — so cards are looked up exactly, and rules are navigated.

---

## Keeping it current

Riot updates the rules per set. When that happens:

```bash
npm run oracle process -- --only=rules
npm run oracle extract
cd .claude/skills/rules-report/lib && python3 rules_cli.py build && python3 rules_cli.py selftest
```

`rules.json` is committed on purpose: a rules update then arrives as a **reviewable diff of rule
IDs** rather than as a wrong citation discovered months later. The 2026-07-16 update renumbered much
of the 400s (Movement 440→445, Scoring 462-467→467-472), which is exactly the kind of change that
silently invalidates saved answers.

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
src/                     TypeScript pipeline (fetch, parse, normalise)
  processors/            one per source type: riftcodex, rules-hub, pdf, html, url
manifests/sources.yaml   prescriptive: what gets fetched and where it lands
output/                  the generated corpus
scripts/pdf-extract.py   pdfplumber PDF → text
.claude/skills/rules-report/
  SKILL.md               the procedure your agent follows
  lib/                   rules_cli.py and the deterministic tools
  reports/               generated HTML reports (gitignored)
```
