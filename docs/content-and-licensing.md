# Content and licensing

Riftbound is a trademark of Riot Games. **This project is unofficial and not endorsed by
Riot.**

## What this repository contains

| | |
|---|---|
| Rules text (Core, Tournament, patch notes, errata) | committed — needed for verifiable citation |
| Card text, stats and artwork **URLs** | committed |
| **Card artwork itself** | **never committed** |
| **Community Q&A** | **never committed, and no longer crawled** |

## Card artwork is referenced, never redistributed

No image file is tracked here. `data/cards.json` holds `image` URLs pointing at Riot's
own CDN, and reports load artwork from there. Without network access the report renders
a labelled placeholder and everything else works normally.

## Community content is neither redistributed nor fetched

A community Q&A corpus was crawled, evaluated and dropped — see
[ADR 0003](adr/0003-tier-1-sources-only.md) for the measurements. The crawler and every
artifact derived from it have been removed, so nothing here quotes or scrapes anyone's
community work.

## Why rules and card text *are* committed

The whole point of this tool is verifying quotes verbatim against a pinned corpus, which
is impossible if the corpus isn't there. Committing `rules.json` additionally means a
rules update arrives as a reviewable diff of rule IDs rather than as a wrong citation
discovered months later.

If you fork this and would rather not redistribute it, delete `output/` and
`.claude/skills/rules-report/data/` — the maintainer commands rebuild everything from
source in a few minutes. The skill will not answer questions until you do.

## Crawling politely

The Rules Hub processor and (historically) the community crawler pace their requests and
send an identifying User-Agent. Riot's Rules Hub sits behind Cloudflare and will reset
connections if hit repeatedly.

**Run updates on demand, never on a schedule.** On `ECONNRESET`, wait or change network
— do not retry into it. This matches Riot's own release cadence, so human-triggered
updates stay well below bot-detection thresholds.
