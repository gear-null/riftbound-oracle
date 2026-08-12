# ADR 0001 — Navigate the rules, don't retrieve over them

**Status:** accepted · **Date:** 2026-08

## Context

The obvious build for "answer questions about a rulebook" is retrieval: chunk the
corpus, embed or index it, retrieve the top-k for a question, hand those to a model.
We built that first.

## Measurement

Lexical (BM25 / SQLite FTS5) retrieval over the rules reached **32% recall@10** on a
620-question benchmark mined from real player questions.

Adding a card→rules query bridge made it *worse* — 28.4% — because OR-ing card-derived
terms into the query diluted it.

## Why it fails

The failure is structural, not a tuning problem:

- **65%** of real questions name a card.
- Of 860 card base names, **109 (12.7%)** appear anywhere in rule text — and nearly all of
  those are incidental collisions with ordinary words (`Block`, `Cull`, `Shadow`), not the
  rules discussing a card. No rule names a card as a card.

Players ask in **card** vocabulary ("does Windsinger target across battlefields?").
The rules are written in **rules** vocabulary. Searching a rulebook for a card name
looks for words that cannot be there. The gap runs one way, so no amount of reranking
closes it.

## Decision

Cards are looked up **exactly**; rules are **navigated**.

The agent resolves named cards against card data, reads their printed text, maps
printed keywords onto glossary sections, and then walks the rule tree — parents,
children, cross-references — until it can state the governing rule. `grep` remains
available as a locating tool, but it is explicitly not evidence of absence.

## Consequences

- The rule tree must be addressable and complete, which is why the corpus is parsed
  into 3,300+ ids rather than chunked.
- Card lookup must be exact and must refuse near-misses. A substring match once
  returned "Shadow" for the nonexistent "Shadowfang Reaper" with no warning; an agent
  handed the wrong card's text reasons confidently about a card nobody asked about.
- The benchmark that produced these numbers was derived from a community corpus that
  is no longer shipped (see [ADR 0003](0003-tier-1-sources-only.md)), so the 32% figure
  is recorded history rather than something you can re-run here. The *reason* is still
  checkable: grep the shipped corpus for any card name.
