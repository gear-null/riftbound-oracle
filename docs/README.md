# Documentation

**Maintainer and contributor documentation.** None of this is needed to use the skill — for
installing and asking questions, see the [main README](../README.md).

## Working on it

| | |
|---|---|
| [Maintaining the skill](maintaining.md) | Refreshing the corpus after a Riot update, cutting a release, the invariants to preserve |
| [Releasing and the changelog](releasing.md) | How versions, changelog entries and release artifacts are produced |
| [`banner.html`](banner.html) | Source for the README banner — render at 1200×400 @2x to regenerate `riftbound-oracle.png` |

## Reference

| | |
|---|---|
| [How to read a report](report-anatomy.md) | Basis, weakest link, crux, citations, the symbol legend |
| [Content and licensing](content-and-licensing.md) | What is committed, artwork policy, crawling etiquette |

## Decision records

Why the system is built the way it is. Each records what was measured, not just what was
chosen.

| | |
|---|---|
| [0001](adr/0001-navigate-dont-retrieve.md) | Navigate the rules, don't retrieve over them |
| [0002](adr/0002-code-verifies-citations.md) | Code decides whether a citation is real, not the model |
| [0003](adr/0003-tier-1-sources-only.md) | Riot's documents are the only citable source |
| [0004](adr/0004-the-skill-is-the-product.md) | The skill is the product; the repo is the workshop |
| [0005](adr/0005-generate-the-rulebook.md) | Generate the anchored rulebook from the parsed corpus |
| [0006](adr/0006-derive-the-symbol-legend.md) | Derive the symbol legend from the rules |
