# Maintaining the skill

Only needed when Riot ships a rules update or a new set, and only by whoever maintains
the skill's data. Users just take the newer folder.

This is the one place the Node pipeline is required.

## The update run

```bash
npm install && npm run build

npm run oracle process -- --only=rules   # refetch the Rules Hub  (network)
npm run oracle extract                   # rulebook PDFs -> markdown
npm run oracle process -- --only=cards   # refetch card sets      (network)
npm run oracle skill-data                # rebuild data/cards.json

cd .claude/skills/rules-report/lib
python3 rules_cli.py build               # re-parse -> data/rules.json, index, rulebook
python3 rules_cli.py selftest            # must end "all N checks passed"
```

`build` regenerates `data/rules.json`, the FTS index and `data/rules.html` together.
They must move as a set: report citations link to `rules.html#CR-<id>`, and a rules
update renumbers IDs.

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

## Repository layout

```
.claude/skills/rules-report/   <- THE PRODUCT. Copy this folder; nothing else is needed.
  SKILL.md                     the procedure an agent follows
  lib/                         rules_cli.py and the deterministic tools
  data/                        vendored + committed (~2.6MB)
  reports/                     generated HTML reports (gitignored)

                               --- maintainer side ---
src/                     TypeScript pipeline (fetch, parse, normalise)
  processors/            one per source type: riftcodex, rules-hub, pdf, html, url
  skill-data.ts          builds data/cards.json
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
