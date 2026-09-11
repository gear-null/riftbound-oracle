# ADR 0009 — The engine plays; card text is executed from verified scripts

**Status:** proposed · **Date:** 2026-09 · Partially supersedes [ADR 0007](0007-the-table-not-the-player.md)

## Context

deck-lab is a table (ADR 0007): code holds the state and an LLM plays every move and
applies every card by hand. That was the right split for a tool whose first job was to
never imagine a draw. It is the wrong split for the job the tool now has: **building
decks against the current tournament meta**, which needs hundreds of games per question,
played competently on both seats.

Measured on the current table (Irelia vs Viktor, seed 7): a state view is 2,442 bytes,
one action render 1,668 bytes; a game is roughly 120 renders, and each call re-reads the
game so far, so a single hand-played game costs on the order of millions of tokens, for a
4-game sample whose Wilson interval SKILL.md itself says is 30–95%. The same design plays
both seats with one mind, has no lookahead, and does not model the chain, where 115 of
954 cards live.

A seven-lens research sweep (recorded in [the engine plan](../plans/riftbound-engine.md),
§5) found the shape that works at this scale: a fast deterministic engine, determinized
search over sampled opponent hands with a beam over turn plans, a small learned
evaluator, and LLMs kept out of the per-decision loop. It also found the failure modes:
card-scripting projects die of silent partial coverage (an existing C++ Riftbound engine
reports 41% of its cards with a real gap under a card-level metric), and LLM agents
playing card games directly score at random.

## Decision

1. **The engine plays.** Code makes every decision through a **decision-request API**:
   the engine runs the rules until a choice is needed and emits a decision with the
   enumerated legal options and the seat's information set; humans, agents, random and
   greedy policies and search are all clients of the same interface. Legal moves are
   generated, never merely validated.
2. **Card text is executed, from scripts that are data.** A script is a JSON program over
   a small closed vocabulary whose primitives are the Core Rules' own game actions
   (413–444). Every script carries rule citations per primitive, clause-level coverage
   marks, scenario tests, and a version hash recorded in every game log it touches. A
   script is **quarantined** until its tests pass, an independent judge accepts it, and a
   mutant of it makes a test fail. Unaccepted cards resolve manually through the table's
   primitives, and the log says so.
3. **Coverage is measured at clause level and by decks engine-ready**, never as "cards
   with a script".
4. **Placement.** The engine lives inside `.claude/skills/deck-lab/lib/engine/`, pure
   Python 3.9+ with no third-party packages, so copying the skill folder remains the
   whole install (ADR 0004). Training, tuning, the ladder, the exploiter and the LLM
   compiler are maintainer-side under `engine-train/` and only write vendored data files.
5. **Speed policy.** The Python engine is the reference and the product. A Rust port of
   the kernel inner loop is permitted only for maintainer-side data generation, must pass
   differential tests against the Python reference, and is gated on a throughput
   measurement with PyPy tried first.
6. **No LLM in the per-decision loop.** LLMs compile card text into scripts offline,
   propose evaluator features and deck mutations, adjudicate flagged nodes as cached
   rulings that become tests, and explain results. They never pick a play.
7. **This is a deck-building tool, not a rules-enforcement service.** The kernel's
   fidelity target is the meta's cards correct, unknown cards refused, corner cases only
   when a puzzle or ruling shows they change results. The opponent set is the versioned
   tournament gauntlet. Pilot quality is part of every verdict, and a meta-respect test
   (known tournament lists beat known casual lists in self-play) gates publication of any
   deck verdict.
8. **Distribution posture.** Riot's Riftbound developer policy prohibits, for API-key
   holders, automated rule enforcement, standalone clients and retaining metagame-defining
   data. This project holds no Riot key: card data comes from Riftcodex under the fan
   content policy. The engine is a private research and deck-building tool, published as
   code, and its self-play tables are simulation output, framed as such. Artwork policy is
   unchanged ([content and licensing](../content-and-licensing.md)).

## Consequences

- ADR 0007's first half stands: nothing that must not be imagined is imagined. Its second
  half — card text is never executed — is superseded. The objection it recorded (a
  mis-scripted card produces a plausible game) is answered by making scripts data that is
  cited, tested, mutated and quarantined, not by avoiding execution.
- Games cost zero tokens. Tokens move to one-off scripting (about 1.6M for the meta pool)
  and to analysis.
- The table stays as one client of the engine and as the differential-testing oracle for
  the shared subset; `do` keeps working.
- Every strength or deck claim is reported as two numbers: games and interval, gauntlet
  score and exploiter score. The perfect-symmetry self-play test must read exactly
  50.00%; anything else is an engine bug, not noise.
- The plan's gates (G1–G5, G-pilot, G-search) decide the open questions by measurement
  rather than by argument: whether determinization fits this game, whether Python is fast
  enough, whether a learned evaluator earns its place.
