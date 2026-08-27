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
  ├── decks.ts            Pulls competitive decklists from rift-atlas
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
6. `npm run oracle skill-data` — rebuilds every skill's vendored card data (needs network)
7. `npm run oracle decks pull` — pulls current tournament decklists into `output/decks/`
8. `npm run oracle vault-sync` — optional; mirrors `output/` into an Obsidian wiki's `raw/`
9. Answer questions via the `rules-report` skill (see `.claude/skills/rules-report/SKILL.md`).
   It writes two documents: a **ruling** (a disputed situation) and a **primer**
   (how a mechanic works, with a diagram derived from its cited transitions).

## Environment Variables

- `RIFTCODEX_API_URL` — Riftcodex API base URL (default: `https://api.riftcodex.com`)
- `VAULT_RAW_DIR` — optional Obsidian wiki `raw/` folder for `vault-sync` (no default)
- `RIFTBOUND_CORPUS` — optional override for where the rules-report skill reads the corpus
  (defaults to this repo's `output/`)

## Design decisions live in docs/

Rationale is recorded once, in [`docs/`](docs/README.md), so it does not drift between
copies. Read these before changing the corresponding behaviour:

| | |
|---|---|
| [ADR 0001](docs/adr/0001-navigate-dont-retrieve.md) | Why there is no retrieval layer |
| [ADR 0002](docs/adr/0002-code-verifies-citations.md) | Why code, not the model, decides a citation is real |
| [ADR 0003](docs/adr/0003-tier-1-sources-only.md) | Why Riot's documents are the only citable source |
| [ADR 0004](docs/adr/0004-the-skill-is-the-product.md) | Why everything is vendored into the skill folder |
| [ADR 0005](docs/adr/0005-generate-the-rulebook.md) | Why the rulebook is generated, not converted from PDF |
| [ADR 0006](docs/adr/0006-derive-the-symbol-legend.md) | Why the symbol legend is derived from the rules |
| [ADR 0008](docs/adr/0008-two-document-kinds.md) | Why there are two document kinds, and why the diagram is derived |

[`docs/maintaining.md`](docs/maintaining.md) has the rules-update procedure, the
repository layout, and the invariants that must hold when editing the skill —
particularly that **nothing in the answering path may reach outside the skill folder at
import time**.

[`docs/content-and-licensing.md`](docs/content-and-licensing.md) covers what is
committed, the artwork policy, and crawling etiquette.

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

## Agentic Engineering Practices

- **All new features must include unit tests.** Don't write token/trivial tests — focus on tests that verify meaningful behavior and catch real regressions. If a feature has logic worth building, it has logic worth testing.
- **Before finishing any task, ensure all tests pass and there are no errors.** Run the full test suite and fix any failures before considering work complete. Do not leave broken tests for someone else to clean up.
