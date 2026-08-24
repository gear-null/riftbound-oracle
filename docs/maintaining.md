# Maintaining the skill

Only needed when Riot ships a rules update or a new set, and only by whoever maintains
the skill's data. Users just take the newer folder.

This is the one place the Node pipeline is required.

## What CI can and cannot refresh

**Neither upstream is reachable from hosted CI.** Measured, twice each:

| | from an ordinary connection | from a GitHub runner |
|---|---|---|
| Riot's Rules Hub | reachable | connection refused (http 000) |
| Riftcodex API | reachable on every User-Agent | **403**, consistently |

Both sit behind Cloudflare, and it is the IP rather than the agent string. Getting past that
would mean evading a bot protection, which is not something this project should do to save a
person one command.

So **checking upstream is a local task**:

```bash
npm run oracle watch          # one request; says what moved, or that nothing did
npm run oracle watch -- --write   # record the new state after regenerating
```

`.github/workflows/watch.yml` does the full detect → regenerate → open-a-PR flow and is kept
for manual dispatch. It works unchanged on a self-hosted runner, or if the block ever lifts.
It is deliberately **not scheduled**: a nightly job that can only ever report "could not check"
either goes red every morning until people ignore it, or reports all-clear through an entire
set release.

The PR reports whether the corpus verified. A new set usually ships equipment whose granted
effect the API omits, which fails the selftest by design — that failure is reported rather than
suppressed, and it is the signal to run `oracle gear-gaps`.

## The update run

```bash
npm install && npm run build

npm run oracle process -- --only=rules   # refetch the Rules Hub  (network)
npm run oracle extract                   # rulebook PDFs -> markdown
npm run oracle process -- --only=cards   # refetch card sets      (network)
npm run oracle skill-data                # rebuild data/cards.json  (network)

cd .claude/skills/rules-report/lib
python3 rules_cli.py build               # re-parse -> data/rules.json, index, rulebook
python3 rules_cli.py selftest            # must end "all N checks passed"
```

`skill-data` writes card data to **both** skills that vendor it — `rules-report` and
`deck-lab` — from one fetch, so the two can never end up disagreeing about what a card
says. Adding a third skill that needs cards means adding it to `CARD_DATA_TARGETS`, not
copying the file.

The deck-lab gauntlet refreshes on its own cadence, because it tracks tournament results
rather than Riot releases:

```bash
npm run oracle decks pull                # tournament decklists     (network)
cd .claude/skills/deck-lab/lib
python3 deck_cli.py selftest             # must end "N/N passed"
python3 deck_cli.py mutants              # must end "N/N mutants caught"
```

`mutants` is the gate that makes `selftest` mean something: it reintroduces each defect
the suite claims to catch and asserts the named check goes red. A surviving mutant is a
check that is lying about what it covers. It is slow — a full suite run per mutant — so
it is a pre-merge gate, not an inner loop.

`build` regenerates `data/rules.json`, the FTS index and `data/rules.html` together.
They must move as a set: report citations link to `rules.html#CR-<id>`, and a rules
update renumbers IDs.

## Card text the API does not carry

Equipment gear prints its granted effect — a "+N Might" badge, sometimes rules text — in a
band at the foot of the card. None of it reaches the Riftcodex API: `text.plain`,
`text.rich` and `media.accessibility_text` all stop after the `[Equip]` clause,
`attributes.might` is null, the OpenAPI schema has no other field, and Riot's Sanity dataset
is private. It exists only on the artwork. No alternative API was found.

It is therefore transcribed once, by hand, into `manifests/card-overlays.yaml`, and folded in
by `skill-data`. **The pipeline itself stays deterministic and model-free** — regeneration
reads a committed file, so a clone or a CI run needs no LLM and no key.

Filling it after a set release:

```bash
npm run oracle gear-gaps     # downloads the artwork + writes a pre-filled stub
```

Open the images in `gear-gaps/`, type the numbers into `overlay-stub.yaml`, move completed
entries into `manifests/card-overlays.yaml`, re-run `skill-data`. Cards you have not covered
stay flagged rather than silently short, and are named on every run and by the selftest.

Verify against the image before adding an entry. A wrong transcription is worse than a
flagged gap: the gap is honest, the transcription is not.

## Errata beats the card database

Card text comes from Riftcodex, which lags Riot by months — it served Stalking Wolf's
pre-errata wording long after the correction was published. Riot's errata is already in this
repo: the Rules Hub crawl writes it into `output/rules.md` as `[NEW TEXT]` blocks.

`skill-data` applies it. Where the two disagree on **wording**, Riot wins and the card records
`errata` provenance, which the report shows. Notation-only differences are left alone, since
the errata prints `[1][C]` where the API sends `:rb_energy_1:` and rewriting every reprint
would churn the corpus for nothing.

**Order matters:** crawl the rules before rebuilding cards, or there is no errata to apply and
`skill-data` warns that card text may be stale. The update run below is already in that order.

## Packaging a release

```bash
npm run oracle package        # -> dist/riftbound-rules-report-v<version>.zip + .sha256
```

The archive is **byte-reproducible**: every entry is stamped with a fixed timestamp, so
building the same corpus twice gives the same checksum. A rebuild that changes nothing is
visibly a no-op, and a release checksum means something.

It carries `SKILL-VERSION.json` recording the rules version, rule and card counts, the commit
it was built from, and how many cards still await transcription — so a downloaded skill,
cut off from this repository, can still be dated against a rules update.

`dist/` is gitignored. The archive is distributed by attaching it to a GitHub release, not by
committing it.

Install from the archive: unzip it into `.claude/skills/`, or upload the zip wherever your
agent takes skills. It needs Python 3.9+ and nothing else.

## Read the diff

`data/rules.json` is committed precisely so an update is reviewable. The 2026-07-16
update renumbered much of the 400s — Movement 440→445, Scoring 462-467→467-472 — which
is exactly the kind of change that silently invalidates saved answers and breaks anchor
links. Skim the ID diff before committing.

## Rate limiting

Riot's Rules Hub sits behind Cloudflare and will reset connections if hit repeatedly.
Run updates **on demand, never on a schedule**. On `ECONNRESET`, wait or change network
rather than retrying into it.

## What must stay true

The selftest enforces most of this, but when changing the skill, keep in mind:

- **Nothing in the answering path may reach outside the skill folder at import time.**
  A module-scope call that resolves the source corpus makes a copied skill unimportable.
- **Build artifacts must be regenerable from vendored data alone.** `rules.db` derives
  from `data/rules.json` and is built on demand; it must never become a prerequisite
  that only the source repo can satisfy.
- **Presentation must never invent a document.** A citation's document comes from the
  rule that actually resolved, never from a default — 790 IDs exist only in the
  Tournament Rules.
- **`build` is maintainer-only.** Don't document it as a user step.
- **A shared check has one definition.** Both document kinds verify the corpus stamp,
  `considered_rejected`, `rules_checked`, card `rule_sections`, citation shape, id
  uniqueness and the required keys. Those
  live once, in `render_report.py`, and `render_primer.py` calls them. Copying one to
  "adapt it" is how three citation-tally comprehensions drifted into disagreeing about
  the same answer file.
- **A diagram is derived or it does not ship.** `flowgraph.py` reads `steps` and
  `exits` and nothing else. Do not add a field that lets an author place an edge, a
  node or a label — see [ADR 0008](adr/0008-two-document-kinds.md). The same rule
  governs anything downstream: `graph` refuses on an unverified primer so that a
  picture can never travel further than its citations.
- **Re-verify every shipped primer after a rules update.** `selftest` does it —
  each `lib/*-primer.json` is asserted whole: every citation verbatim, the
  transitions still a procedure, and the report, the map and the export still
  agreeing on every transition number. A renumbering invalidates a committed
  document silently, and these are the documents a reader opens first.
- **Sweep the guards after any batch of guard work.** Delete each `if` that
  refuses, reports or bails, and run the suite: anything that stays green is
  pinned by nothing. 25 of 59 did here. Most were display paths; the rest were
  guards no check had ever walked, plus two that masked each other. The
  technique and the reason are in [invariants.md](invariants.md).
- **Then probe shapes no fixture produces.** A sweep can only test code that
  exists — it cannot flag a missing rule, because there is no line to neuter.
  Degenerate DOCUMENTS are the analogue of a degenerate board: an empty step
  id, a whitespace heading, a quote spanning two sibling rules, a corpus
  stamped with a version that does not exist. That probe is what found `all()`
  short-circuiting the citation loop, where a failing quote hid every
  fabrication after it in the same block.
- **The IR is the product; the renderer is not.** Fireworks Tech Graph lives outside
  the skill folder, so nothing here may require it. `graph` always writes the IR —
  self-contained, checkable, diffable — and renders an SVG only if an install is
  found (`$RIFTBOUND_FIREWORKS` overrides the search). A missing install must cost a
  picture, never an answer. Do not add a hard dependency on it.
- **Do not hand Fireworks a prompt.** It accepts natural language, and that path is
  closed here on purpose: a described diagram is a model-authored diagram, and
  invariant 12 is the whole reason a picture is publishable at all. Style 8, the
  closest match to this project's palette, is refused for exactly this reason —
  Fireworks will only hand-craft it.
- **The deck-lab table must refuse rather than assume.** A permissive table produces
  confident wrong games, which is worse than no table — see
  [ADR 0007](adr/0007-the-table-not-the-player.md). When adding an action, decide what it
  does when the rules forbid it *before* deciding what it does when they allow it.
- **The table must never interpret card text.** It may print text verbatim and it may
  refuse; the moment it starts applying an effect, every card it does not handle becomes
  a silent wrong answer instead of a visible manual step.
- **Every deck-lab behaviour needs a mutant, not just a check.** Adding a rule to the
  table means adding a check to `selftest.py` AND a mutant to `mutants.py` that has been
  seen to make that check fail. The first run of the battery found five checks that
  passed while the behaviour they named was deleted.
- **A turn must stay cheap.** Card text prints once per game, batches are one round trip,
  and SKILL.md carries everything a normal turn needs so playing never requires a rules
  lookup. Count the tool calls a feature costs before counting the rules it covers.

## Repository layout

```
.claude/skills/rules-report/   <- THE PRODUCT. Copy this folder; nothing else is needed.
  SKILL.md                     the procedure an agent follows
  lib/                         rules_cli.py and the deterministic tools
    verify_citations.py        the verbatim gate — shared by both document kinds
    render_report.py           a RULING, plus the checks and chrome both kinds share
    render_primer.py           a PRIMER: steps, transitions, misconceptions
    flowgraph.py               derives a primer's diagram from its cited transitions
    fireworks_ir.py            the same graph as Fireworks IR, for export
  data/                        vendored + committed (~2.6MB)
    diagrams/                  the shipped primers' diagrams, and the IR they came from
  reports/                     generated HTML reports (gitignored)

.claude/skills/deck-lab/       <- THE OTHER PRODUCT. Same deal: copy the folder.
  SKILL.md                     the procedure for building and testing a deck
  lib/                         deck_cli.py — table, deck legality, shuffle math
  data/cards.json              vendored + committed, written by `oracle skill-data`
  gauntlet/                    tournament decklists, committed
  decks/                       decks under construction
  games/, reports/             working artifacts (gitignored)

                               --- maintainer side ---
src/                     TypeScript pipeline (fetch, parse, normalise)
  processors/            one per source type: riftcodex, rules-hub, pdf, html, url
  skill-data.ts          builds cards.json for every skill that vendors it
  decks.ts               pulls decklists into output/decks/
manifests/sources.yaml   prescriptive: what gets fetched and where it lands
output/                  intermediate corpus the skill data is built from
scripts/pdf-extract.py   pdfplumber PDF -> text
docs/                    these documents
```

## Environment variables

| | |
|---|---|
| `RIFTCODEX_API_URL` | Riftcodex API base (default `https://api.riftcodex.com`) |
| `RIFTBOUND_CORPUS` | override where the rebuild path reads source markdown |
| `VAULT_RAW_DIR` | optional Obsidian wiki `raw/` folder for `vault-sync` |
