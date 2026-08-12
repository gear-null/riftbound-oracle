# ADR 0002 — Code decides whether a citation is real, not the model

**Status:** accepted · **Date:** 2026-08

## Context

A confident answer citing `471.1.b` is worthless if that rule says something else, or
does not exist. Measured over 7,774 community-written answers to real Riftbound
questions: of the 831 that cite a rule ID, **29% of those citations point at an ID that
does not exist at all.** Not misread — absent.

Riftbound has a property that makes something better possible: every atomic claim in
the rules already has a canonical address like `471.1.b.1`. So the system can cite
**rules**, not text fragments, and then check them mechanically.

## Decision

The division of labour is fixed: **the agent decides what to look at; code decides
whether the citations it produced are real.**

`verify_citations.py` checks, cheapest first:

| check | meaning |
|---|---|
| **exists** | the cited id is a real rule at this corpus version |
| **quote** | the quoted span appears verbatim in that rule or its subtree |
| **narrow** | a vague cite is pushed down to the tightest rule whose own text says it |
| **document** | the id is labelled with the document it actually resolved in |

If any citation the holding depends on fails, the disposition is **forced to
UNSETTLED** and the report will not render. The model cannot outrun its own verifier.

## Consequences

- An answer is only finished when `rules_cli.py report` has run. Splitting verify and
  render meant an answer could be left as a JSON file plus homework.
- Abstention is audited to the same standard as assertion: a note claiming the rules
  are silent must list what it searched.
- Confidence is `min()` across claims, never an average. One structural step makes the
  whole answer structural.
- Several real defects have come from the *labelling* layer rather than the check
  itself — a bare id resolving in Tournament Rules was once stamped "Core Rules" with a
  green verified badge. Anything that presents a citation must derive the document from
  the resolved rule, never from a default.
