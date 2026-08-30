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
                                         # read the line under it too — it says
                                         # how many of those N have ever failed
cd ../../../..
python3 site/build.py                    # the site is DERIVED from the corpus
python3 site/build_test.py               # and its verifiers must still fail
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

A rules update moves `data/rules.html` and `data/rules.json`, which the website
embeds and quotes — so the site must be rebuilt and committed in the same commit.
Skip it and the Pages workflow refuses to publish, correctly, because what is
committed no longer matches the corpus it claims to describe.

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

## Adding a check, and keeping the gate green

`scripts/check-invariants.py` is a required CI step and it exits non-zero on a
gap. A check enters the record only when the battery has WATCHED it fail, so a
commit that adds a check to an invariant's fragment list, without also
committing a `proven-checks.json` that covers it, turns CI red on main.

The order that works:

1. add the check, and a mutant that reintroduces the defect it names
2. run `python3 rules_cli.py mutants` and confirm the mutant is caught
3. commit the code, the mutant, AND the regenerated `proven-checks.json`
   **together**

Splitting step 3 leaves main red between the two commits, and the failure reads
"1 invariant not fully pinned" — which is alarming, correct, and easy to
misread as a regression by anyone who was not there.

## Packaging a release

Both skills ship together. `oracle package` builds an archive per skill —
`riftbound-rules-report-vX.zip` and `riftbound-deck-lab-vX.zip` — each with its own
`SKILL-VERSION.json` and `.sha256`, and `install.sh` fetches both by default
(`--skill <name>` for one). A release carries every shipping skill or it carries none:
packaging was hardcoded to one of them for a while, and the other quietly had no release
archive at all. `install.test.ts` now asserts the installer handles every skill the
packager produces, and that check has been seen to fail.

deck-lab's manifest records what a rulebook cannot: how many gauntlet decks it carries and
the date they were pulled. A gauntlet of tournament lists goes stale on its own clock, and
an installed copy is cut off from the repo that could say so.


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

- **To find every site, trace routes to output — do not enumerate callers.** Both
  answer "where does this reach a human", and only one of them is honest. Grepping
  `cards.text(` finds sites that *name* the function; it cannot find
  `deck_cli.py:155`, which prints card text and never mentions the function that
  produced it, because the value arrived in a dict from somewhere else. The
  route-tracing sweep — walk every `json.dump`, every `.write(`, every serialiser,
  every `["text"]` — found that one plus three tails the caller list had no way to
  raise: whether the HTML report prints text or only counts, whether `--json`
  exposes it, and whether it is persisted into saved games (it is not, so there is
  no migration).

  This is the guard sweep's lesson one level up: a search shaped like the code you
  expect cannot see code written another way. Enumerating callers is the cheap
  first pass; it is not the coverage argument.

- **Pin a measured pattern against being made NARROWER, not only wider.** The
  widenings are the ones you go looking for, so they get guarded. The tightening
  arrives disguised as tidying: `[)\]][A-Z]` looks careless, and requiring a
  lowercase tail after the capital looks like an obvious improvement. It silently
  drops 20 cards, because Riftbound speaks in the first person and the sentence
  after the seam opens on a bare `I` — `…enter ready.)I have [Assault]…`. That is
  not hypothetical: two independent measurements of the same defect disagreed by
  exactly that set before anyone noticed the tail was doing it.

  Any regex encoding a measured decision can be improved into a worse one by
  someone cleaning it up. If the measurement was worth making, mutate the
  tightening too, and let the check name the set that would be lost.

- **Never match on `str(exception)`; match on `err.args[0]`.** `str(KeyError(msg))`
  is `repr(msg)`, and `repr` picks its wrapper from the content. A message holding
  only single quotes comes back wrapped in double ones, inner quotes intact, so a
  match on `saved game 'x'` fires. Put a double quote anywhere else in that same
  message — nest another error's text, quote a filename — and repr flips to
  single-quote wrapping and escapes every inner single quote, and the identical
  match silently stops firing. Nothing goes red; the check simply never fires
  again.

  That is worse than escaping unconditionally, which fails while you are writing
  the check and looking straight at it. This one passes when written and dies
  later, from an edit that appears unrelated and lands in someone else's commit.
  The wrapper defeats `startswith`/`endswith` on a raw `str()` too. The whole
  class disappears if the predicate reads `args[0]`, so make that the habit
  rather than reasoning about which row you are in. It is a check-that-cannot-fail
  with a cause unlike the others here: not a behaviour with no check behind it,
  but a predicate that cannot become true no matter what the code does.

  The one raise that breaks the habit is the argumentless one: `raise KeyError()`
  leaves `args` empty, so `args[0]` is an `IndexError`. Every raise in both skills
  passes exactly one f-string, so nothing is exposed, and this is not worth a
  guard while that convention holds. Note which way it fails, though — `args[0]`
  crashes, where `str()` returns `''` and quietly matches nothing. Loud is the
  better failure, so the habit stays right even in the row that breaks it.
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
- **A second guard makes the system safer and the suite blinder.** Redundant guards are
  good; only their safety is visible. Delete either half of a masking pair and nothing goes
  red, so a one-at-a-time mutant battery reports both as covered while neither is pinned.
  When you add a guard behind an existing one, add the check that tells them APART at the
  same time — assert on which message fired, not merely that something refused. A guard
  indistinguishable from the guard behind it cannot be pinned separately, and if the two
  print the same string you have to make them differ before you can check them.

  The sweep that finds these is cheap and worth re-running after any batch of guard work:
  neuter each `raise` in turn and see whether the suite still passes. It found **20 of 37
  unpinned** in deck-lab, including a 144.2 move-cost refusal masked by `exhaust()`'s own
  complaint. (Credit to `riftbound-oracle-c1`, which found the same class on the
  rules-report side — a `cmd_report` gate whose docstring called it "the ONLY way to finish
  an answer", pinned by nothing.)

- **The guard sweep only finds code you wrote; probe for states you never build.** A
  battery over `raise` sites cannot flag a rule with no code behind it at all, because
  there is no line to neuter. The complement is to construct board shapes no fixture
  produces and ask whether each is refused, handled, or silently wrong: negative Might, a
  Victory Score of zero, both players on the target at once, a draw of nothing, a
  battlefield contested by a player with no units, every rune recycled, a unit parked in
  the opponent's base. Ten such probes found 323.7 missing — a permanent in a foreign base
  was never recalled, so a unit walked into the enemy base stayed there for the rest of the
  game, reading on the board as a presence it does not have. Nine of the ten were already
  correct, which is the expected yield; the probe is cheap enough that the ratio is fine.

  Two habits make the probes pay. Assert on the **log**, not just on state, when the two
  cannot be told apart: recalling a unit to the base it already occupies moves nothing, so
  a check on `location` passes whether or not the sweep wrongly picked it up — the mutation
  battery caught exactly that weak check here. And write a mutant per **clause**, not per
  rule: 323.7 has one condition for foreign bases and one for unattached Gear, and each of
  the two conditions has an over-broad failure as well as an off one, so a single rule
  earned five mutants.

- **Narrow where you delete, wide where you only report — and let them disagree.**
  `stripTrailingArtifact` removes a stray token from card text and is anchored and
  conservative, because a false positive destroys a real card's rules text. The
  corpus-integrity check that scans for the same signature is deliberately wider,
  because reporting cannot destroy anything. When the wide one fires on something the
  narrow one ignores, that is the check working: look at the card. Widening the deleter
  until its detector goes green leaves you with a deleter and no detector, since a check
  derived from what it checks can only find what that thing already does.
- **Seeds pair, they do not multiply.** Each seat shuffles on its own generator derived
  from the seed, so at a fixed seed a seat draws the same cards whatever it is facing —
  two decks can be compared over identical opposition. That is a paired design, not an
  independent one: reusing a seed across decks does NOT give you independent samples, and
  a run that read 18 such games as independent was really six situations played three
  times. Vary the seed for independence.
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
