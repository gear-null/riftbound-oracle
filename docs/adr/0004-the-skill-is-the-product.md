# ADR 0004 — The skill is the product; the repo is the workshop

**Status:** accepted · **Date:** 2026-08

## Context

The project began as a processing pipeline whose output happened to feed an answering
skill. That inverted the value: the thing people want is the answerer, and it was
unusable without cloning a Node repo, installing dependencies and running a build.

Concretely, the skill folder reached outside itself for almost everything — card data
came from the repo's `output/cards-*.md`, artwork URLs from a separate generated
`card-index.json`, and the rule index from a gitignored build artifact. A copied skill
silently lost card lookup entirely, rendered artwork placeholders, and had a dead
`grep`.

## Decision

`.claude/skills/rules-report/` is the shipped artifact. **Copying that one folder is
the entire install** — no Node, no build, no network, no API key.

Everything it needs is vendored in `data/` and committed:

| file | what it is |
|---|---|
| `data/rules.json` | the parsed rulebook, 3,300+ addressable rules |
| `data/cards.json` | card text, structured stats and artwork URLs |
| `data/rules.html` | the anchored rulebook reports link into |

The TypeScript pipeline in `src/` is the **maintainer** side. It fetches from Riot and
Riftcodex and regenerates those three files. Nothing in the answering path touches it.

## Consequences

- Nothing in the answering path may resolve a module or a file outside the skill folder
  at import time. `parse_rules.py` once resolved the source corpus at module scope,
  which meant a copied skill could not even import it — taking the whole selftest down
  with it, though only two of its checks touch the parser.
- Build artifacts must be regenerable from vendored data alone. `rules.db` (the FTS
  index) derives entirely from `data/rules.json`, so it is built on demand rather than
  committed.
- `build` is a maintainer command. Documentation must not tell a user to run it; in a
  shipped install it is a traceback.
- Data files are committed on purpose. `rules.json` in particular means a rules update
  arrives as a **reviewable diff of rule IDs** rather than as a wrong citation
  discovered months later.
- The skill costs ~2.6MB. That is the price of working offline on first use, and it is
  the right trade for a tool whose whole promise is that you can check its work.
