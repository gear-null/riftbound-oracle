# ADR 0006 — Derive the symbol legend from the rules, and don't replace the shorthand

**Status:** accepted · **Date:** 2026-08

## Context

Rules text is dense with bracketed shorthand. `[E]: Add [Y].` is unreadable until you
know it means "exhaust this: add one Power of Order", and a reader meeting it cold has
no way in.

Two questions: where does the key come from, and should the report substitute real
symbols for the shorthand?

## Decision

**The legend is derived from the corpus, not hardcoded.** Riot defines each shorthand
in the rules themselves — CR 134.2 for the six domains (with their colours), CR 135.2.e
for exhaust / might / any-domain / own-domain / the keyword marker, CR 429.5 for bare
numbers. `symbols.py` parses those rules, so every legend entry can cite the rule that
defines it.

**The shorthand is left exactly as Riot prints it.** `[A]` stays `[A]`. The report ends
with a key covering only the symbols on that page.

## Rationale

A hand-written symbol table is a second source of truth that rots silently. Deriving it
means a renumbering, a reworded definition or a seventh domain updates the legend on its
own — and the selftest fails loudly if a domain stops being derivable.

On substitution: the goal is a reader who gradually stops needing the legend and can
then read Riot's own PDFs unaided. Replacing the shorthand with glyphs would make this
one report legible while leaving the source material no easier.

## Consequences

- Scanning must be narrow. Rules text is also full of bracketed prose — `[Warning]`,
  `[do X]`, `[Reaction]`, 76 distinct bracket tokens in all — and glossing those turns a
  key into noise. Only tokens already in the derived legend, plus bare numbers, qualify.
- The scan runs over the finished page and must unescape first: the keyword marker is
  written into HTML as `[&gt;]`, so scanning raw markup silently never matched the one
  symbol a reader is least likely to guess.
- Card text must use the same shorthand as the rules, or the report contradicts itself.
  Unmapped `:rb_rune_*:` shortcodes were once replaced with a space, deleting a card's
  cost outright while the note beside it quoted the errata as "costs [2][A][A]".
