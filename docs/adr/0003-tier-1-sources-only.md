# ADR 0003 — Riot's documents are the only citable source

**Status:** accepted · **Date:** 2026-08

## Context

The intuition behind a second tier is that when the official rules run out, community
Q&A is the nearest thing to an answer — especially where a designer has weighed in.

We tested that rather than assuming it. A 7,774-answer community corpus (RiftJudge) was
crawled, stamped per-entry as unofficial, and measured.

## Measurement

Over all 7,774 answers:

| | |
|---|---|
| Mention Riot | **5** (0.06%) |
| Cite a dev or designer | **5** (0.06%) |
| Flag a coming rules change | **13** (0.2%) |
| Admit the rules don't settle it | **4** (0.05%) |
| Cite a rule ID at all | **831** (10.7%) |

Of those 831 citing answers (1,239 citations between them), **29%** of the citations
point at a rule ID that does not exist, and **33%** of the answers contain at least one
such ID.

## Decision

**Tier 1 only.** Riot's Core Rules, Tournament Rules, patch notes and errata, plus
Riftcodex card data. No community Q&A, no FAQ scrape, no forum archive.

When the rules genuinely don't settle a question, the answer is `UNSETTLED` with the
gap named.

## Rationale

The case for a second tier is that it relays designer intent or marks where the rules
run out. This corpus did neither at any useful rate — while answering confidently
regardless, which is the exact failure mode this project exists to remove.

It also produced a concrete error: a "take control" exception to banishment that
`829.1.b` flatly contradicts, which was believed and written into a draft wiki page
before the abstention test caught it.

Practically, it could not be *navigated* either. At ~1.1M tokens it was reachable only
by the retrieval path already rejected in [ADR 0001](0001-navigate-dont-retrieve.md).

## Consequences

- The crawler and every artifact derived from it are removed. Nothing community-authored
  is redistributed or fetched.
- `SKILL.md` states this positively — "there is no second-tier source" — because an
  agent that meets an empty result needs to recognise it as a finding, not a gap in
  its search.
- The 620-pair retrieval benchmark was mined from this corpus and went with it. That is
  the real cost of the decision: the 32% recall figure is no longer reproducible here.
- If a genuinely official second source appears (a Riot FAQ archive, a judge digest), it
  needs the same treatment the rules get: verbatim text, addressable units, and
  per-entry provenance — retrieval surfaces a chunk without its file header, so a
  file-level "unofficial" banner does not travel with the text.
