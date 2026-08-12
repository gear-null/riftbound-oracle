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
npm run oracle skill-data                # rebuild data/cards.json  (network)

cd .claude/skills/rules-report/lib
python3 rules_cli.py build               # re-parse -> data/rules.json, index, rulebook
python3 rules_cli.py selftest            # must end "all N checks passed"
```

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
