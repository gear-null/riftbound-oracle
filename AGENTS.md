# Riftbound Oracle

A pipeline that turns Riftbound TCG source material (cards, rules, tournament
guidelines) into a structured, addressable corpus, plus a Claude Code skill that
answers rules questions against it with mechanically verified citations.

## Architecture

```
sources/          → Raw inputs (PDFs, HTML, JSON) — gitignored, manually gathered
  ├── cards/
  ├── rules/
  └── tournament/

output/           → Processed markdown — checked into git, source of truth
manifests/        → Prescriptive source config + processing state (sources.yaml)

src/              → TypeScript pipeline
  ├── cli.ts              Main CLI entrypoint (clack-based)
  ├── riftcodex.ts        Riftcodex API client + card→markdown
  ├── manifest.ts         Read/write sources.yaml
  ├── normalize.ts        Common markdown cleanup + entity decoding
  ├── print.ts            Downloads card images for proxy printing
  ├── vault.ts            Optional Obsidian vault mirror
  └── processors/
      ├── index.ts        Router: file extension → processor
      ├── pdf.ts          Shells out to Python script (async with progress)
      ├── html.ts         Uses jsdom + turndown for HTML→markdown
      ├── url.ts          Fetches URL, then jsdom + turndown
      ├── api.ts          JSON card data → markdown
      └── rules-hub.ts    Crawls the Rules Hub, splits PDFs from articles

scripts/
  └── pdf-extract.py      Python PDF→text via pdfplumber (reports page progress)

.claude/skills/rules-report/
  ├── SKILL.md            The procedure an LLM agent follows to answer a question
  └── lib/                rules_cli.py + the deterministic verification tools
```

## Tech Stack

- **Runtime:** Node.js 22+
- **Language:** TypeScript
- **Build:** Vite 8 (library mode, ES format)
- **CLI:** @clack/prompts
- **PDF extraction:** Python 3 + pdfplumber (called as subprocess)
- **HTML→MD:** jsdom + turndown
- **Config format:** YAML (manifests)
- **Testing:** vitest

## Conventions

- Use ES modules (`"type": "module"` in package.json)
- Prefer `node:` prefix for built-in modules (`node:fs`, `node:path`, etc.)
- Keep processors stateless — each takes options and writes to the specified output path
- All output markdown gets a YAML frontmatter header (category, generated date, generator name)
- Manifest is prescriptive: it declares all sources and their output targets

## Manifest (manifests/sources.yaml)

The manifest is the single source of truth for what gets processed. Each entry declares:
- **type**: `riftcodex`, `pdf`, `html`, `json`, `url`, or `rules-hub`
- **category**: `cards`, `rules`, `tournament`, `errata`
- **output**: target markdown file path
- **processed**: date last processed (set automatically, absent = pending)

Type-specific fields:
- `riftcodex` entries have `set_id`
- `pdf`/`html`/`json` entries have `path` (local file) and optional `url` (provenance)
- `url` entries have `url` (fetched live during processing)
- `rules-hub` entries have `url` (hub landing page); the processor auto-discovers
  linked PDFs, downloads them into `output/`, and records the paths in a `pdfs: []`
  field for traceability. `extract` and `vault-sync` pick PDFs up by scanning
  `output/`, not by reading that field

## Workflow

1. Edit `manifests/sources.yaml` to declare sources
2. Place local files (PDFs, HTML) into `sources/` if needed
3. `npm run oracle process` — processes all entries from the manifest
4. `npm run oracle process -- --only=rules` — filter by category or output path
5. `npm run oracle extract` — turns downloaded rulebook PDFs into markdown in `output/`
6. `npm run oracle card-index` — optional; fetches card artwork URLs for report rendering
7. `npm run oracle vault-sync` — optional; mirrors `output/` into an Obsidian wiki's `raw/`
8. Answer questions via the `rules-report` skill (see `.claude/skills/rules-report/SKILL.md`)

## Environment Variables

- `RIFTCODEX_API_URL` — Riftcodex API base URL (default: `https://api.riftcodex.com`)
- `VAULT_RAW_DIR` — optional Obsidian wiki `raw/` folder for `vault-sync` (no default)
- `RIFTBOUND_CORPUS` — optional override for where the rules-report skill reads the corpus
  (defaults to this repo's `output/`)

## The skill is the product

`.claude/skills/rules-report/` is the shipped artifact. Someone copies that one folder into their
project and it answers questions offline with no clone, no build and no network, because
everything it needs is vendored in `data/`:

| file | what it is | rebuilt by |
|---|---|---|
| `data/rules.json` | 3,316 parsed, addressable rules | `rules_cli.py build` |
| `data/cards.json` | card text + artwork URLs | `npm run oracle skill-data` |
| `data/rules.html` | anchored rulebook that report citations link into | `rules_cli.py rulebook` |

All three are committed. Ignoring any of them breaks the copy-and-go promise.

The TypeScript pipeline in `src/` is the **maintainer** side: it fetches from Riot and Riftcodex
and regenerates the files above. Nothing in the answering path touches it. When editing the skill,
keep it that way — a `from corpus import source_corpus_dir` at module scope is enough to make a
copied skill unusable, which is exactly how `parse_rules.py` once took the whole selftest down.

**Reports link into the rulebook by relative path** (`../data/rules.html#CR-471.1.b.1`). The anchor
scheme lives in `render_rulebook.anchor()` and `render_report.py` imports it rather than
re-deriving the format — one definition, so the two cannot drift. `selftest` asserts every emitted
link resolves to a real anchor.

## Only Riot's documents are citable

`rules.md`, `core-rules.pdf`, `tournament-rules.pdf` and the Riftcodex card data are the entire
source set. There is no second tier — no community Q&A, no FAQ scrape, no forum archive.

When the rules don't settle a question, the answer is `UNSETTLED` with the gap named. Not a
confident answer sourced from somewhere weaker, and not an interaction recalled from elsewhere.

This was tested rather than assumed. A 7,774-answer community Q&A corpus was crawled, measured
and dropped: 0.06% of its answers mentioned Riot, 0.2% flagged a coming rules change, and 0.05%
admitted the rules didn't settle the question — so it never did the job (relaying designer
intent, marking gaps) that would justify a second tier, while answering confidently regardless.
Of the 831 answers that cited a rule ID, 29% of those citations pointed at a rule that doesn't
exist. It also propagated a concrete error into a draft of the wiki: a "take control" exception
to banishment that `829.1.b` flatly contradicts.

**Don't reintroduce one casually.** If a genuinely official source appears (a Riot FAQ archive, a
judge digest), it needs the same treatment the rules get: verbatim text, addressable units, and
per-entry provenance — retrieval surfaces a chunk without its file header, so a file-level
"unofficial" banner does not travel with the text.

## Obsidian wiki sync

`vault-sync` mirrors `output/` into an LLM-maintained wiki's `raw/` source layer
(that vault has its own `AGENTS.md` describing the ingest/query/lint model).
Two properties make it safe to run often:

- **PDFs are extracted to text**, not copied — the wiki cites readable source.
- **Files compare with the `generated:` date stripped**, so re-rendering
  unchanged source reports "unchanged" instead of rewriting every file. Real
  drift stays visible instead of being buried in date churn.

It only creates or updates, never deletes — `raw/` may hold curated sources
this pipeline doesn't manage. Syncing is only half the job: changed sources
still need an agent to ingest them into the wiki's `pages/`.

## Card artwork is referenced, never redistributed

`oracle card-index` writes `output/card-index.json` — a map of card name to the artwork URL on
Riot's CDN. **That file is gitignored**: it is generated per-user, and shipping a curated index of
Riot asset URLs is not this repo's business. No image binary is ever tracked (`print/` and
`sources/**` are both ignored).

The report renderer embeds `<img src="<riot cdn url>">`, so artwork is fetched from Riot at view
time rather than copied here. When the index is absent — a fresh clone, or a blocked network — the
renderer emits a labelled placeholder and the report is otherwise complete. **Never make artwork a
hard dependency of rendering.**

Rules text and card text ARE committed, deliberately: verifying quotes verbatim against a pinned
corpus is the entire premise, and that is impossible if the corpus is not present.

## Key Decisions

- **One markdown file per set/document**, not per card — keeps the corpus greppable and diffable
- **sources/ is gitignored** (except READMEs) — raw PDFs/HTML are temporary; only processed markdown is tracked
- **Manifest is checked in** — provides traceability and is the prescriptive config for processing
- **Python is only used for PDF extraction and the rules-report skill** — the pipeline is TypeScript
- **Card artwork is referenced by URL, never stored** — see above
- **`rules.json` is committed on purpose** — a rules update then arrives as a reviewable diff of
  rule ids rather than as a wrong citation discovered months later

## Updates are agent-driven, not scheduled

Riot's Rules Hub and news site sit behind Cloudflare, which will rate-limit or
block clients that iterate too fast (we've seen persistent `ECONNRESET` from a
source IP after just a few back-to-back full runs). The processor handles the
actual fetching and parsing deterministically, but **runs should be triggered
on demand by a human or agent — never on a cron or schedule**.

Typical update flow:

1. Human asks an agent (e.g. Claude Code): "update the Riftbound rules."
2. Agent runs the right slice, e.g. `npm run oracle process -- --only=rules`.
3. On `ECONNRESET` / 403 / similar block, the agent asks the user to switch
   networks (mobile tether reliably works) or waits, rather than retrying
   blindly and deepening the block.
4. Agent sanity-checks `output/rules.md` and any downloaded PDFs before
   rebuilding the index (line counts, section headers, known noise absent).
5. Agent runs `npm run oracle extract`, then rebuilds the rules index and runs
   `rules_cli.py selftest`.
6. Agent reports what changed in the corpus.

This matches Riot's own release cadence (set or patch drops), so human-
triggered updates stay below bot-detection thresholds in practice.

**Do not** replace the processor's HTML/PDF parsers with LLM summarization.
The rules answerer verifies quotes verbatim against this corpus — paraphrased
or abstracted content makes every citation fail, and worse, makes a citation
that passes meaningless.

## Agentic Engineering Practices

- **All new features must include unit tests.** Don't write token/trivial tests — focus on tests that verify meaningful behavior and catch real regressions. If a feature has logic worth building, it has logic worth testing.
- **Before finishing any task, ensure all tests pass and there are no errors.** Run the full test suite and fix any failures before considering work complete. Do not leave broken tests for someone else to clean up.
