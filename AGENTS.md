# Riftbound Oracle

A processing pipeline that converts manually curated Riftbound TCG source material (cards, rules, tournament guidelines) into structured markdown, then syncs it to Google Drive for consumption by NotebookLM.

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
  ├── normalize.ts        Common markdown cleanup
  ├── upload.ts           Google Drive sync, dedupe, cleanup
  └── processors/
      ├── index.ts        Router: file extension → processor
      ├── pdf.ts          Shells out to Python script (async with progress)
      ├── html.ts         Uses jsdom + turndown for HTML→markdown
      ├── url.ts          Fetches URL, then jsdom + turndown
      ├── api.ts          JSON card data → markdown
      └── rules-hub.ts    Crawls the Rules Hub, splits PDFs from articles

scripts/
  └── pdf-extract.py      Python PDF→text via pdfplumber (reports page progress)
```

## Tech Stack

- **Runtime:** Node.js 22+
- **Language:** TypeScript
- **Build:** Vite 8 (library mode, ES format)
- **CLI:** @clack/prompts
- **PDF extraction:** Python 3 + pdfplumber (called as subprocess)
- **HTML→MD:** jsdom + turndown
- **Upload:** googleapis (Google Drive API v3)
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
  linked PDFs and persists their output paths back into a `pdfs: []` field on
  the entry, which the uploader then picks up as separate NotebookLM sources

## Workflow

1. Edit `manifests/sources.yaml` to declare sources
2. Place local files (PDFs, HTML) into `sources/` if needed
3. `npm run oracle process` — processes all entries from manifest
4. `npm run oracle process -- --only=tournament` — filter by category or output path
5. `npm run oracle upload` — syncs `output/` to Google Drive folder
6. `npm run oracle drive-status` — list every file the app can see in the folder
7. `npm run oracle cleanup [--confirm]` — dry-run (or delete) orphans and duplicates
8. NotebookLM reads from the Drive folder (configured once, manually)

## Environment Variables

- `GOOGLE_APPLICATION_CREDENTIALS` — path to Google service account key JSON
- `DRIVE_FOLDER_ID` — Google Drive folder ID for upload target
- `RIFTCODEX_API_URL` — Riftcodex API base URL (default: `https://api.riftcodex.com`)

## Key Decisions

- **One markdown file per set/document**, not per card — NotebookLM has a 50-source limit (free tier)
- **sources/ is gitignored** (except READMEs) — raw PDFs/HTML are temporary; only processed markdown is tracked
- **Manifest is checked in** — provides traceability and is the prescriptive config for processing
- **Python is only used for PDF extraction** — everything else is TypeScript
- **Google Drive is a mirror**, not the source of truth — never edit files in Drive directly

## Updates are agent-driven, not scheduled

Riot's Rules Hub and news site sit behind Cloudflare, which will rate-limit or
block clients that iterate too fast (we've seen persistent `ECONNRESET` from a
source IP after just a few back-to-back full runs). The processor handles the
actual fetching and parsing deterministically, but **runs should be triggered
on demand by a human or agent — never on a cron or schedule**.

Typical update flow:

1. Human asks an agent (e.g. Claude Code): "update the Riftbound rules."
2. Agent runs the right slice, e.g. `npm run oracle process --only=rules`.
3. On `ECONNRESET` / 403 / similar block, the agent asks the user to switch
   networks (mobile tether reliably works) or waits, rather than retrying
   blindly and deepening the block.
4. Agent sanity-checks `output/rules.md` and any downloaded PDFs before
   uploading (line counts, section headers, known noise absent).
5. Agent runs `npm run oracle upload`, then `drive-status` / `cleanup` to
   confirm Drive ended up clean.
6. Agent reports which Drive files changed.

This matches Riot's own release cadence (set or patch drops), so human-
triggered updates stay below bot-detection thresholds in practice.

**Do not** replace the processor's HTML/PDF parsers with LLM summarization.
NotebookLM needs verbatim source text for citations — paraphrased or
abstracted content will cause citations to drift from what's actually in
Riot's published documents.

## Agentic Engineering Practices

- **All new features must include unit tests.** Don't write token/trivial tests — focus on tests that verify meaningful behavior and catch real regressions. If a feature has logic worth building, it has logic worth testing.
- **Before finishing any task, ensure all tests pass and there are no errors.** Run the full test suite and fix any failures before considering work complete. Do not leave broken tests for someone else to clean up.
