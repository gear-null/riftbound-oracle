# ADR 0005 — Generate the anchored rulebook from the parsed corpus

**Status:** accepted · **Date:** 2026-08

## Context

Reports cite rules by ID. A citation could be *expanded* in place to show its ancestor
spine, but not *followed* — there was nowhere to go. The obvious route to a
followable link is to convert Riot's published PDF to HTML and add anchors.

## Decision

Don't touch the PDF. Render `data/rules.html` from `data/rules.json`, giving every one
of the 3,316 rules a stable anchor (`id="CR-471.1.b.1"`).

## Rationale

The parsed corpus is strictly better input than the PDF:

- **One source of truth.** The anchor scheme and the IDs the verifier checks citations
  against come from the same data, so a citation and its link cannot disagree.
  `render_report.py` imports `render_rulebook.anchor()` rather than re-deriving the
  format.
- **Cross-references become links.** The parser already extracts `see_also`, so "see
  rule 367" inside rule text is a working link — something the PDF cannot do.
- **A rules update can't silently rot the links.** Regenerating is part of `build`, and
  the selftest asserts that every link a report emits resolves to a real anchor.

## Consequences

- `build` must regenerate the rulebook. It did not at first, so citation links pointed
  into a stale rulebook after a rules update — silently, because a missing fragment
  just lands at the top of the page.
- Reports link relatively (`../data/rules.html#CR-...`), so the pair keeps working
  offline and survives being moved together.
- The rulebook opens in an overlay rather than replacing the report, because reading a
  cited rule should not cost you your place in the argument. It uses an `<iframe>`, not
  `fetch`: `file://` forbids XHR between local files, while an iframe loads and honours
  the `#fragment` natively.
