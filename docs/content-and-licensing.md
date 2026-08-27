# Content and licensing

## The short version

**The code is MIT.** The rules text is Riot's. Those are two different things in one
repository, and [LICENSE](../LICENSE) says which is which — you cannot MIT-license
someone else's copyright, so this project does not pretend to.


Riftbound is a trademark of Riot Games. **This project is unofficial and not endorsed by
Riot.**

## What this repository contains

| | |
|---|---|
| Rules text (Core, Tournament, patch notes, errata) | committed — needed for verifiable citation |
| Card text, stats and artwork **URLs** | committed |
| **Card artwork as a file** | **never committed** — see the screenshot note below |
| **Community Q&A** | **never committed, and no longer crawled** |

## Card artwork is referenced, never redistributed

No artwork asset is tracked here. `data/cards.json` holds `image` URLs pointing at Riot's
own CDN, and reports load artwork from there at view time — which means **opening a report
makes an outbound request to `cmsassets.rgpub.io`**. Offline, the card falls back to a
labelled "artwork offline" placeholder and everything else works normally.

**One exception, stated plainly:** `docs/images/report.png` is a screenshot of a rendered
report, and two card faces are visible inside it. It is documentation of the tool, not a
usable art asset, but it is a committed image containing Riot artwork and the table above
would otherwise read as absolute.

The repository banner, `riftbound-oracle.png`, is not an exception: it is drawn from this
project's own design system by `docs/banner.html`, and the only Riot content on it is one
rule quotation already committed to the corpus.

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

If you fork this and would rather not redistribute it, delete `output/`, `.claude/skills/rules-report/data/` and `docs/images/` — the maintainer commands rebuild everything from
source in a few minutes. The skill will not answer questions until you do.

## Crawling politely

The Rules Hub processor, the decklist puller and (historically) the community crawler
pace their requests and send an identifying User-Agent. Riot's Rules Hub sits behind
Cloudflare and will reset connections if hit repeatedly.

`oracle decks pull` reads `rift-atlas.com`, one deck page at a time with a 1.2s gap —
about 30 seconds for the whole meta index. It was chosen over the alternatives because it
server-renders complete decklists as plain semantic HTML: no deck API exists anywhere,
and Piltover Archive resets scripted connections outright, which is a clear enough signal
not to work around. Decklists are card names and counts — facts about a tournament
result, not Riot's copyrighted text — and each pulled deck records the URL and date it
came from.

A deck whose page does not parse cleanly is **not written**. Overwriting a good committed
list with a half-rendered one loses data that was correct, so those are reported by name
and left out; a named hole in the gauntlet is recoverable and silent corruption is not.

**Run updates on demand, never on a schedule.** On `ECONNRESET`, wait or change network
— do not retry into it. This matches Riot's own release cadence, so human-triggered
updates stay well below bot-detection thresholds.
